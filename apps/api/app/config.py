"""Central settings. No hardcoded keys, model names, thresholds, or score weights.

Everything the rest of the app needs to configure itself lives here, sourced
from the environment (see .env.example / AGENTS.md "Environment").
"""

from __future__ import annotations

from functools import lru_cache
from typing import Literal

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

VectorBackend = Literal["memory", "pinecone-local", "pinecone"]
LLMProvider = Literal["openai", "anthropic", "gemini"]
Env = Literal["dev", "demo", "eval"]


class ScoringWeights(BaseSettings):
    """PRD §9 scoring formula weights. Must sum to 1.0."""

    must_have_coverage: float = 0.50
    nice_to_have_coverage: float = 0.20
    semantic_similarity: float = 0.15
    depth_signal: float = 0.15


class ScoringThresholds(BaseSettings):
    """PRD §9 recommendation thresholds."""

    advance_min: float = 0.70
    review_min: float = 0.45
    ambiguous_band_low: float = 0.45
    ambiguous_band_high: float = 0.65


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # LLM provider
    llm_provider: LLMProvider = "openai"
    openai_api_key: str | None = None
    anthropic_api_key: str | None = None
    gemini_api_key: str | None = None
    openai_model: str = "gpt-4o-mini"
    anthropic_model: str | None = None
    # Free-tier-friendly Gemini model (Google AI Studio API key, no billing
    # required). Deliberately a "-latest" alias, not a pinned version: the
    # newest pinned models (e.g. gemini-3.8-flash) returned repeated 503
    # "high demand" errors live, while this alias worked first try and
    # still supports structured output (response_schema) — verified live
    # against the real API, not assumed. Aliases also sidestep the
    # "model no longer available" 404s a pinned name eventually hits as
    # Google retires versions. Override via GEMINI_MODEL if needed.
    gemini_model: str = "gemini-flash-lite-latest"
    llm_temperature: float = 0.0

    # Relational DB. Host port is 5433 locally (docker-compose.yml maps
    # 5433->5432 to avoid colliding with a native/Homebrew Postgres that may
    # already own 5432 on the host); containers reach it as db:5432 instead.
    database_url: str = "postgresql+psycopg://skillbridge:skillbridge@localhost:5433/skillbridge"

    # Langfuse
    langfuse_public_key: str | None = None
    langfuse_secret_key: str | None = None
    langfuse_host: str = "http://localhost:3001"

    # Vector store
    vector_backend: VectorBackend = "memory"
    pinecone_api_key: str | None = None
    pinecone_dense_index: str = "skillbridge-dense"
    pinecone_sparse_index: str = "skillbridge-sparse"
    pinecone_env: Env = "dev"
    pinecone_local_host: str = "http://localhost:5080"

    # Models
    embedding_model: str = "llama-text-embed-v2"
    embedding_dimension: int = 1024
    sparse_model: str = "pinecone-sparse-english-v0"
    rerank_model: str = "bge-reranker-v2-m3"
    rerank_enabled: bool = False

    # Optional
    github_token: str | None = None

    # Scoring (PRD §9) — overridable via env for eval sweeps, never hardcoded in callers
    scoring_weights: ScoringWeights = Field(default_factory=ScoringWeights)
    scoring_thresholds: ScoringThresholds = Field(default_factory=ScoringThresholds)

    scoring_min_confidence: float = Field(default=0.5, ge=0, le=1)
    keyword_stuffing_ratio_threshold: float = Field(default=0.8, ge=0, le=1)
    keyword_stuffing_min_skills: int = Field(default=5, ge=1)
    keyword_stuffing_max_penalty: float = Field(default=0.10, ge=0, le=1)
    scoring_depth_values: dict[str, float] = Field(
        default_factory=lambda: {
            "list_only": 0.2,
            "coursework": 0.5,
            "project": 0.8,
            "production": 1.0,
        }
    )

    # Freshness wait (PRD §8.6)
    vector_freshness_timeout_s: float = 15.0

    # Upsert batching (AGENTS.md "Pinecone rules")
    pinecone_upsert_batch_size: int = 100
    pinecone_upsert_max_retries: int = 3

    # Hybrid retrieval (PRD §8.4, M1 app/rag/retriever.py)
    rrf_k: int = 60
    retriever_top_k: int = 20
    retriever_final_k: int = 5

    # Intake worker (PRD §13 — a simple poller, deliberately not a task
    # queue; see PROGRESS.md decisions)
    worker_poll_interval_s: float = 3.0

    copilot_confidence_threshold: float = Field(default=0.7, ge=0, le=1)
    copilot_max_grounding_retries: int = Field(default=2, ge=0, le=2)
    copilot_pool_limit: int = Field(default=10, ge=1, le=50)
    copilot_max_evidence_chunks: int = Field(default=12, ge=1, le=50)
    github_timeout_s: float = Field(default=5.0, gt=0, le=15)
    github_max_repos: int = Field(default=10, ge=1, le=30)
    copilot_stream_poll_s: float = Field(default=0.25, gt=0)
    copilot_stream_timeout_s: float = Field(default=120.0, gt=0)

    # Applicant upload (PRD F1.2)
    resume_upload_max_mb: float = 5.0
    resume_upload_dir: str = "data/uploads"

    # CORS — the Next.js dev origin needs to call the API directly (no
    # Next.js server-side proxy in M1)
    cors_allow_origins: list[str] = Field(default_factory=lambda: ["http://localhost:3000"])


@lru_cache
def get_settings() -> Settings:
    return Settings()
