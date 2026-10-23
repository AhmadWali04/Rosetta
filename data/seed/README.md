# data/seed/

## job.json — status: REAL posting (not a placeholder)

`job.json` is `_placeholder: false`. It transcribes the real, publicly
posted ProCogia role referenced in PRD §6 / F1.1: **"AI Intern, Applied &
Agentic AI" (December 2026 – April 2027), Vancouver BC, on-site**.

### How it was found and verified

The canonical posting lives on ProCogia's Greenhouse job board
(`job-boards.greenhouse.io/procogia`), but that host returns a 302 redirect
to `procogia.com/about-us/careers/` (a JS-rendered listing) for non-browser
fetches, so the raw Greenhouse HTML could not be fetched directly in this
session. Instead, the posting was verified via web search
("ProCogia AI Intern Applied Agentic AI Greenhouse") and cross-checked
across **two independent job-board mirrors that both source from the same
Greenhouse posting**:

- https://zapply.jobs/jobs/bf8fd104-1412-4ac7-a773-3f0795031ce1/ — includes
  a working "Apply via Greenhouse" embed link
  (`job-boards.greenhouse.io/embed/job_app?for=procogia&...`), confirming
  this mirror is sourced directly from ProCogia's Greenhouse board.
- https://interninsider.me/internships/procogia/ai-intern-applied-agentic-ai-ac243664-5ce6-4dd0-b837-788d3ba83970

Both mirrors agree on title, location, employment dates, hourly pay
(CAD $23/hr), responsibilities, and the must-have/nice-to-have
qualifications (phrased slightly differently but substantively identical —
expected, since each site paraphrases the same underlying Greenhouse
content rather than serving the raw HTML). A third source,
https://www.dreamworkhq.com/job/303e1a9b-aa1d-49a3-b169-7ad5dbe41fb9,
corroborates the role summary and tech stack (Python, OpenAI/Anthropic
models) via web search results.

`requirements[]` in job.json merges and lightly consolidates the
must-have/nice-to-have lists from those two mirrors (8 bullets condensed to
6 must-haves, the "nice-to-have" paragraph split into 4 discrete bullets)
so each requirement is a single, matchable claim. Weights (1.0–2.0 for
must-haves, 0.5–1.0 for nice-to-haves) are this session's judgment call
about relative importance and are HR-editable per PRD §7.1's footnote —
they are not sourced from the posting, which doesn't publish weights.

If a more authoritative transcription (e.g. a direct screenshot or saved
copy of the live Greenhouse page) becomes available, replace
`raw_description` and `requirements[]` with the verbatim text and update
this note — don't silently drop the sourcing trail above.

## skills.json → see `data/taxonomy/README.md`

That file documents scope and sourcing for the skills taxonomy used by the
Skill Normalizer / taxonomy RAG namespace.

## Re-running the seed

`apps/api/scripts/seed.py` is idempotent: it deletes and re-inserts the
`Job` row with a fixed id (`job-ai-intern-procogia`) and its
`JdRequirement` rows, and wipes/reinserts all of `SkillTaxonomy`, every
time it runs. Safe to re-run after editing either JSON file. See the
Makefile's `make seed` target for the exact invocation.
