"""Configurazione applicativa caricata dall'ambiente.

I valori arrivano dalle variabili d'ambiente (vedi `.env.example`).
Nessun segreto è hardcoded: tutto passa da qui.

Provider LLM primario: OpenAI. L'architettura resta predisposta al
multi-provider, ma la v1 usa OpenAI per generazione ed embedding e
LlamaParse per il parsing dei documenti in fase di ingestion.
"""

from pydantic_settings import BaseSettings, SettingsConfigDict


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
    wc_consumer_key: str = ""
    wc_consumer_secret: str = ""

    # ChromaDB
    chroma_host: str = "chromadb"
    chroma_port: int = 8000
    chroma_collection: str = "woo_knowledge"

    # Sessione
    session_secret: str = "change-me-in-production"


settings = Settings()
