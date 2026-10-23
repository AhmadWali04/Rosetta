"""Unit tests for `app.rag.chunking.chunk_sections` (PRD §7.1 "Chunk &
Index", §8.3 record metadata). Pure Python, no network.

Run with: `cd apps/api && uv run pytest tests/rag/test_chunking.py -v`
"""

from __future__ import annotations

import tiktoken

from app.graphs.state import Section
from app.rag.chunking import chunk_sections

_ENCODING = tiktoken.get_encoding("cl100k_base")


def _repeat_words(word: str, count: int) -> str:
    return " ".join(f"{word}{i}" for i in range(count))


def test_empty_sections_list_returns_no_chunks() -> None:
    assert chunk_sections([]) == []


def test_single_short_section_produces_one_chunk_with_exact_text_and_offsets() -> None:
    text = "Built a RAG pipeline with LangChain and Pinecone."
    section = Section(name="experience", text=text, char_start=100, char_end=100 + len(text))

    chunks = chunk_sections([section], target_tokens=300, overlap_tokens=50)

    assert len(chunks) == 1
    chunk = chunks[0]
    assert chunk.section == "experience"
    assert chunk.text == text
    assert chunk.char_start == 100
    assert chunk.char_end == 100 + len(text)
    assert chunk.pinecone_id == ""


def test_chunks_never_span_a_section_boundary() -> None:
    section_a_text = _repeat_words("alpha", 400)
    section_b_text = _repeat_words("beta", 400)
    section_a = Section(
        name="experience", text=section_a_text, char_start=0, char_end=len(section_a_text)
    )
    offset_b = len(section_a_text) + 1  # pretend there's a separator char between sections
    section_b = Section(
        name="projects",
        text=section_b_text,
        char_start=offset_b,
        char_end=offset_b + len(section_b_text),
    )

    chunks = chunk_sections([section_a, section_b], target_tokens=50, overlap_tokens=10)

    assert len(chunks) > 2  # each section should have split into multiple chunks
    for chunk in chunks:
        if chunk.section == "experience":
            assert "beta" not in chunk.text
        else:
            assert chunk.section == "projects"
            assert "alpha" not in chunk.text

    # chunk_idx is assigned sequentially across the whole document.
    assert [c.chunk_idx for c in chunks] == list(range(len(chunks)))


def test_chunk_token_counts_stay_within_target() -> None:
    text = _repeat_words("skill", 500)
    section = Section(name="skills", text=text, char_start=0, char_end=len(text))

    chunks = chunk_sections([section], target_tokens=40, overlap_tokens=5)

    assert len(chunks) > 1
    for chunk in chunks:
        token_count = len(_ENCODING.encode(chunk.text))
        assert token_count <= 40


def test_consecutive_chunks_overlap_when_overlap_tokens_set() -> None:
    text = _repeat_words("project", 500)
    section = Section(name="projects", text=text, char_start=0, char_end=len(text))

    chunks = chunk_sections([section], target_tokens=40, overlap_tokens=10)

    assert len(chunks) > 1
    for prev_chunk, next_chunk in zip(chunks, chunks[1:], strict=False):
        # Overlap means the next chunk starts strictly before the previous
        # chunk ends (consecutive, non-overlapping chunks would have
        # next.char_start >= prev.char_end).
        assert next_chunk.char_start < prev_chunk.char_end
        # But forward progress is still guaranteed.
        assert next_chunk.char_start > prev_chunk.char_start


def test_no_overlap_produces_contiguous_non_overlapping_chunks() -> None:
    text = _repeat_words("task", 300)
    section = Section(name="experience", text=text, char_start=0, char_end=len(text))

    chunks = chunk_sections([section], target_tokens=30, overlap_tokens=0)

    assert len(chunks) > 1
    for prev_chunk, next_chunk in zip(chunks, chunks[1:], strict=False):
        assert next_chunk.char_start >= prev_chunk.char_end


def test_char_offsets_are_reconstructable_against_the_original_section_text() -> None:
    text = _repeat_words("evidence", 300)
    section_char_start = 2048
    section = Section(
        name="experience",
        text=text,
        char_start=section_char_start,
        char_end=section_char_start + len(text),
    )

    chunks = chunk_sections([section], target_tokens=35, overlap_tokens=8)

    assert len(chunks) > 1
    for chunk in chunks:
        rel_start = chunk.char_start - section_char_start
        rel_end = chunk.char_end - section_char_start
        assert 0 <= rel_start <= rel_end <= len(text)
        assert text[rel_start:rel_end] == chunk.text


def test_chunk_idx_is_sequential_across_multiple_sections() -> None:
    sections = [
        Section(name="summary", text=_repeat_words("x", 50), char_start=0, char_end=200),
        Section(name="experience", text=_repeat_words("y", 50), char_start=200, char_end=400),
        Section(name="skills", text=_repeat_words("z", 50), char_start=400, char_end=600),
    ]

    chunks = chunk_sections(sections, target_tokens=20, overlap_tokens=5)

    assert [c.chunk_idx for c in chunks] == list(range(len(chunks)))


def test_empty_section_text_produces_no_chunks() -> None:
    section = Section(name="education", text="", char_start=10, char_end=10)
    assert chunk_sections([section]) == []
