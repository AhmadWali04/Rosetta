# data/taxonomy/

## skills.json — curated subset, not the full O*NET/ESCO datasets

This is a **deliberate M0 scope decision, not corner-cutting**: the real
O*NET "Technology Skills" dataset and the ESCO skills taxonomy are each
thousands of rows (O*NET alone lists tens of thousands of
occupation-to-technology mappings; ESCO has ~13,900 skill/competence
concepts). M0 is about proving the ingestion pipeline — Postgres write →
embed → upsert to Pinecone taxonomy namespace → normalizer RAG lookup —
works end to end, not about dataset completeness. Importing the full
datasets now would mean thousands of embedding calls and rows with no
payoff for the demo, which only ever matches against one seeded JD.

`skills.json` is a JSON array of 170 entries, each:

```json
{
  "canonical": "PyTorch",
  "alt_labels": ["Torch", "PyTorch Lightning"],
  "description": "...",
  "source": "onet" | "esco"
}
```

### Coverage

Programming languages, ML/AI frameworks (including LangChain, LangGraph,
Hugging Face Transformers, the Model Context Protocol), data engineering
(Spark, Airflow, dbt, Kafka, ETL), cloud/infra (AWS/GCP/Azure, Docker,
Kubernetes, Terraform), databases (Postgres, MongoDB, Redis, Pinecone and
other vector DBs), web backend/frontend (FastAPI, Flask, Django, Node.js,
React, REST/GraphQL), and general CS/AI/data-science concepts (RAG,
embeddings, prompt engineering, agent orchestration, NLP, computer vision,
statistics, observability, prompt-injection/LLM security, etc.) — chosen to
realistically cover both this JD's requirements and the kind of skills a
typical tech/AI-intern resume lists.

### `source` field

This is a *structural* label, not a claim that the row is drawn verbatim
from either real dataset: `"onet"` is used for concrete, named
tools/languages/frameworks (mirroring how O*NET's Technology Skills
examples are specific software products), and `"esco"` is used for broader
methodologies/competencies/concepts (mirroring how ESCO frames skills and
competences more abstractly, and is the dataset PRD §8/§10 calls out for
alt-label/synonym coverage). The actual canonical names, alt-labels, and
descriptions were authored from general knowledge of how these taxonomies
are structured — this file does not reproduce official O*NET or ESCO
records.

### Swapping in the full dataset later

Same JSON shape (array of `{canonical, alt_labels, description, source}`).
To upgrade:
1. Download O*NET's Technology Skills table and/or the ESCO skills CSV/RDF
   export.
2. Transform each row into this shape (map O*NET's "Example" field or
   ESCO's altLabels to `alt_labels`).
3. Either overwrite `skills.json` or point `apps/api/scripts/seed.py`'s
   `TAXONOMY_PATH` at a new file — the seeding logic doesn't need to
   change, only the input file (and probably its own `make seed` runtime,
   since thousands of rows means thousands of embedding calls — batch
   accordingly and consider rate limits mentioned in agents.md).
4. Re-run `make seed`. It wipes and reinserts the entire `SkillTaxonomy`
   table and the `{env}-taxonomy` Pinecone namespace every time, so this
   is safe.
