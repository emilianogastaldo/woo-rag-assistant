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
    model_config = SettingsConfigDict(
        env_file=".env", extra="ignore", allow_inf_nan=False, hide_input_in_errors=True
    )

    # LLM (OpenAI)
    openai_api_key: str = ""
    openai_model: str = "gpt-4.1-mini"
    embedding_model: str = "text-embedding-3-small"
    openai_base_url: str | None = None
    provider_timeout_seconds: float = Field(default=15.0, gt=0, le=120)
    provider_retry_attempts: int = Field(default=1, ge=0, le=2)

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
    wc_timeout_seconds: float = Field(default=5.0, gt=0, le=60)
    wc_retry_attempts: int = Field(default=1, ge=0, le=2)

    # ChromaDB
    chroma_host: str = "chromadb"
    chroma_port: int = 8000
    chroma_collection: str = "woo_knowledge"
    knowledge_state_dir: str = "/state/knowledge"
    embedding_dimensions: int = Field(default=1536, ge=1, le=65536)

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
    agent_max_steps: int = Field(default=4, ge=1, le=12)
    agent_max_attempts: int = Field(default=12, ge=2, le=50)
    agent_retry_budget: int = Field(default=2, ge=0, le=8)
    agent_max_repeated_errors: int = Field(default=2, ge=1, le=5)
    request_deadline_seconds: float = Field(default=30.0, gt=0, le=180)

    # Sessione
    session_secret: str = "change-me-in-production"
    session_ttl_seconds: int = Field(default=28800, ge=1)
    app_env: Literal["development", "production"] = "development"
    demo_enabled: bool = False
    conversation_ttl_seconds: int = Field(default=1800, ge=1)
    conversation_capacity: int = Field(default=1000, ge=1)
    conversation_max_turns: int = Field(default=20, ge=1, le=100)
    message_max_bytes: int = Field(default=4000, ge=1, le=16000)
    history_max_bytes: int = Field(default=16000, ge=1, le=100000)
    chat_body_max_bytes: int = Field(default=24000, ge=256, le=200000)
    model_context_max_bytes: int = Field(default=32000, ge=1, le=200000)
    model_token_budget: int = Field(default=100000, ge=1, le=1000000)
    model_max_output_tokens: int = Field(default=512, ge=1, le=4096)
    tool_output_max_bytes: int = Field(default=12000, ge=1, le=100000)
    customer_cache_ttl_seconds: int = Field(default=300, ge=1)
    customer_cache_capacity: int = Field(default=1000, ge=1)
    rate_limit_requests: int = Field(default=20, ge=1)
    rate_limit_window_seconds: int = Field(default=60, ge=1)
    rate_limit_capacity: int = Field(default=10000, ge=1)

    # Origini ammesse per il widget (CORS), separate da virgola
    cors_origins: str = "http://localhost:8080,http://localhost:8000"

    @model_validator(mode="after")
    def validate_security(self):
        if self.app_env == "production":
            if len(self.session_secret.strip()) < 32 or self.session_secret.strip().lower() in {
                "change-me-in-production",
                "change-me",
                "changeme",
                "replace-with-a-random-secret-at-least-32-characters",
            }:
                raise ValueError(
                    "Production requires a non-default SESSION_SECRET of 32+ characters"
                )
            if self.demo_enabled:
                raise ValueError("Demo login is forbidden in production")
        return self

    @property
    def retrieval(self) -> RetrievalConfig:
        return RetrievalConfig(
            **{name: getattr(self, f"retrieval_{name}") for name in RetrievalConfig.model_fields}
        )

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
