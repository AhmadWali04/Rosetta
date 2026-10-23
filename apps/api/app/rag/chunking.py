"""Section-aware chunking (PRD §7.1 "Chunk & Index", §8.3 record metadata).

`chunk_sections()` splits each `Section` (from `app.graphs.state`) into
token-sized `ChunkData` pieces, WITHIN that section only — a chunk never
spans two sections, so `ChunkData.section` is always unambiguous (the Skill
Extractor / Requirement Matcher need to know which part of the resume a
chunk came from without guessing).

Token counting uses `tiktoken`'s `cl100k_base` encoding. This is not
guaranteed to be byte-identical to whichever LLM eventually reads these
chunks (PRD/AGENTS.md: the LLM provider is pluggable, OpenAI or Anthropic),
but accurate, consistent chunk-size boundaries matter far more here than
exact tokenizer parity with one specific future model — `cl100k_base` is
tiktoken's standard, widely-available encoding and is a reasonable proxy
for "roughly this many tokens" across providers.

IMPORTANT for callers (the Chunk & Index node, M1, a different agent):
`ChunkData.pinecone_id` is left as `""` (empty string placeholder) here.
This module has no `application_id` in scope, so it cannot compute the
real record ID. The caller MUST fill in `pinecone_id` afterward, per
record, using `app.rag.namespaces.chunk_record_id(application_id,
chunk.chunk_idx)` — e.g.:

    chunks = chunk_sections(sections)
    chunks = [
        chunk.model_copy(update={"pinecone_id": chunk_record_id(application_id, chunk.chunk_idx)})
        for chunk in chunks
    ]

`char_start`/`char_end` on each `ChunkData` are ABSOLUTE offsets into the
full sanitized document text (i.e. `section.char_start + <offset within
section.text>`), matching what `resume_chunks` stores (PRD §8.3) and what
the Section model's own docstring promises. Nothing renders these until
M2's citation highlighting, but they must be correct now — get them wrong
here and every later citation silently points at the wrong resume text.
"""

from __future__ import annotations

import tiktoken

from app.graphs.state import ChunkData, Section

_ENCODING_NAME = "cl100k_base"


def _encoding() -> tiktoken.Encoding:
    return tiktoken.get_encoding(_ENCODING_NAME)


def chunk_sections(
    sections: list[Section],
    target_tokens: int = 300,
    overlap_tokens: int = 50,
) -> list[ChunkData]:
    """Chunk every section into ~`target_tokens`-sized pieces with
    `overlap_tokens` of token overlap between consecutive chunks WITHIN the
    same section. Chunks never merge text across a section boundary.

    `chunk_idx` is assigned sequentially across the whole document (0, 1,
    2, ...), in section order, matching `IntakeState.chunks`' expected
    shape and `app.rag.namespaces.chunk_record_id`'s `#chunk#{n}` scheme.

    `pinecone_id` is left as `""` on every returned `ChunkData` — see the
    module docstring; the caller must fill it in.
    """
    encoding = _encoding()
    chunks: list[ChunkData] = []
    next_chunk_idx = 0
    for section in sections:
        section_chunks = _chunk_one_section(
            section,
            encoding=encoding,
            target_tokens=target_tokens,
            overlap_tokens=overlap_tokens,
            start_chunk_idx=next_chunk_idx,
        )
        chunks.extend(section_chunks)
        next_chunk_idx += len(section_chunks)
    return chunks


def _chunk_one_section(
    section: Section,
    *,
    encoding: tiktoken.Encoding,
    target_tokens: int,
    overlap_tokens: int,
    start_chunk_idx: int,
) -> list[ChunkData]:
    """Chunk a single section's text. Never reaches outside `section.text`.

    Char offsets are computed by decoding each candidate token slice back
    to text, then LOCATING that exact substring within `section.text`
    (via `str.find`, searching forward from the previous chunk's start) —
    rather than trusting cumulative token-decode lengths directly. tiktoken
    guarantees `decode(encode(text)) == text` for the FULL token list, but
    decoding an arbitrary slice of tokens can in rare cases land mid
    multi-byte character at the boundary; locating the decoded piece back
    in the real source text sidesteps that entirely and guarantees the
    chunk's stored `text` and offsets are always an exact, verifiable
    substring of `section.text`.
    """
    text = section.text
    if not text:
        return []

    tokens = encoding.encode(text)
    total_tokens = len(tokens)
    if total_tokens == 0:
        return []

    # Guarantee forward progress even if overlap_tokens >= target_tokens
    # (a misconfigured caller shouldn't be able to produce an infinite loop).
    step = max(target_tokens - overlap_tokens, 1)

    out: list[ChunkData] = []
    token_start = 0
    search_from = 0
    chunk_idx = start_chunk_idx

    while token_start < total_tokens:
        token_end = min(token_start + target_tokens, total_tokens)
        piece_tokens = tokens[token_start:token_end]
        piece_text = encoding.decode(piece_tokens)

        pos = text.find(piece_text, search_from)
        if pos == -1:
            # Fallback for the rare decode-boundary mismatch described
            # above: fall back to the best-known lower bound rather than
            # failing the whole chunking pass over one ragged edge.
            pos = search_from

        chunk_text = text[pos : pos + len(piece_text)]
        out.append(
            ChunkData(
                chunk_idx=chunk_idx,
                section=section.name,
                text=chunk_text,
                char_start=section.char_start + pos,
                char_end=section.char_start + pos + len(chunk_text),
                pinecone_id="",
            )
        )
        chunk_idx += 1

        if token_end >= total_tokens:
            break
        token_start += step
        # Next chunk's decoded text starts at or after this chunk's own
        # start (tokens only move forward), so searching from `pos` (not
        # `pos + len(chunk_text)`) correctly handles overlapping chunks
        # while still ruling out an earlier, unrelated repeat of the same
        # phrase elsewhere in the section.
        search_from = pos

    return out
