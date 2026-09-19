"""Configurazione applicativa caricata dall'ambiente.

I valori arrivano dalle variabili d'ambiente (vedi `.env.example`).
Nessun segreto è hardcoded: tutto passa da qui.

Provider LLM primario: OpenAI. L'architettura resta predisposta al
multi-provider, ma la v1 usa OpenAI per generazione ed embedding e
LlamaParse per il parsing dei documenti in fase di ingestion.
"""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class RetrievalConfig(BaseModel):
    """Validated, immutable options; no credentials or provider configuration."""

    model_config = ConfigDict(frozen=True, extra="forbid", allow_inf_nan=False)

    strategy: Literal["semantic", "hybrid"] = "semantic"
    k: int = Field(default=4, ge=1, le=100)
    candidates: int = Field(default=12, ge=1, le=1000)
    max_distance: float = Field(default=0.6, ge=0, le=2)
    rrf_constant: int = Field(default=60, ge=1)
    semantic_weight: float = Field(default=1.0, gt=0)
    lexical_weight: float = Field(default=1.0, gt=0)
    bm25_k1: float = Field(default=1.5, gt=0)
    bm25_b: float = Field(default=0.75, ge=0, le=1)
    lexical_min_score: float = Field(default=1.0, gt=0)
    lexical_min_coverage: float = Field(default=1.0, gt=0, le=1)
    retry_attempts: int = Field(default=0, ge=0, le=1)

    @model_validator(mode="after")
    def check_candidates(self):
        if self.candidates < self.k:
            raise ValueError("retrieval candidates must be >= k")
        return self


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # LLM (OpenAI)
    openai_api_key: str = ""
    openai_model: str = "gpt-4.1-mini"
    embedding_model: str = "text-embedding-3-small"

    # Document parsing (LlamaParse / LlamaCloud)
    llama_cloud_api_key: str = ""

    # WooCommerce REST (read-only)
    wc_base_url: str = "http://wordpress/wp-json/wc/v3"
    # URL pubblico (home_url di WordPress) usato per la base string della firma
    # OAuth: WooCommerce la ricostruisce dal proprio home_url, non dall'host a cui
    # ci si connette. In Docker ci si connette a wc_base_url (http://wordpress) ma
    # si firma con wc_sign_url (es. http://localhost:8080). Vedi docs DEC-001.
    # Se vuoto, coincide con wc_base_url.
    wc_sign_url: str = ""
    wc_consumer_key: str = ""
    wc_consumer_secret: str = ""

    # ChromaDB
    chroma_host: str = "chromadb"
    chroma_port: int = 8000
    chroma_collection: str = "woo_knowledge"

    # RAG: numero di chunk recuperati e distanza massima (coseno, 0=identico)
    # oltre la quale un chunk è considerato non pertinente. Vedi docs DEC-005:
    # la soglia va calibrata con `evals/run_eval.py`.
    retrieval_k: int = 4
    retrieval_max_distance: float = 0.6
    retrieval_strategy: Literal["semantic", "hybrid"] = "semantic"
    retrieval_candidates: int = 12
    retrieval_rrf_constant: int = 60
    retrieval_semantic_weight: float = 1.0
    retrieval_lexical_weight: float = 1.0
    retrieval_bm25_k1: float = 1.5
    retrieval_bm25_b: float = 0.75
    retrieval_lexical_min_score: float = 1.0
    retrieval_lexical_min_coverage: float = 1.0
    retrieval_retry_attempts: int = 0
    chunk_size: int = 800
    chunk_overlap: int = 120

    # Agente: tetto ai giri di tool calling per singola richiesta
    agent_max_steps: int = 4

    # Sessione
    session_secret: str = "change-me-in-production"
    session_ttl_seconds: int = 28800

    # Origini ammesse per il widget (CORS), separate da virgola
    cors_origins: str = "http://localhost:8080,http://localhost:8000"

    @property
    def retrieval(self) -> RetrievalConfig:
        return RetrievalConfig(**{
            name: getattr(self, f"retrieval_{name}")
            for name in RetrievalConfig.model_fields
        })

    @model_validator(mode="after")
    def validate_retrieval(self):
        _ = self.retrieval
        return self

    @property
    def wc_signing_base(self) -> str:
        """Base URL per la firma OAuth (fallback su wc_base_url se non impostato)."""
        return self.wc_sign_url or self.wc_base_url

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]


settings = Settings()
