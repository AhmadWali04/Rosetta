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
LLMProvider = Literal["openai", "anthropic"]
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

    # Relational DB
    database_url: str = "postgresql+psycopg://skillbridge:skillbridge@localhost:5432/skillbridge"

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

    # Freshness wait (PRD §8.6)
    vector_freshness_timeout_s: float = 15.0

    # Upsert batching (AGENTS.md "Pinecone rules")
    pinecone_upsert_batch_size: int = 100
    pinecone_upsert_max_retries: int = 3


@lru_cache
def get_settings() -> Settings:
    return Settings()
