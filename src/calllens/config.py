from pydantic_settings import BaseSettings, SettingsConfigDict
from pydantic import PostgresDsn, RedisDsn, computed_field
from uuid import UUID


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    # Postgres — superuser connection (migrations / ingestion seed)
    postgres_host: str = "localhost"
    postgres_port: int = 5432
    postgres_db: str = "calllens"
    postgres_user: str = "calllens"
    postgres_password: str = "calllens_dev"

    # App-level DB user (FastAPI / workers — honours RLS)
    postgres_app_user: str = "calllens_app"
    postgres_app_password: str = "calllens_app_dev"

    @computed_field
    @property
    def database_url(self) -> str:
        return (
            f"postgresql+asyncpg://{self.postgres_user}:{self.postgres_password}"
            f"@{self.postgres_host}:{self.postgres_port}/{self.postgres_db}"
        )

    @computed_field
    @property
    def database_url_sync(self) -> str:
        return (
            f"postgresql://{self.postgres_user}:{self.postgres_password}"
            f"@{self.postgres_host}:{self.postgres_port}/{self.postgres_db}"
        )

    @computed_field
    @property
    def app_database_url(self) -> str:
        """URL for the limited-privilege app user — used by API and workers."""
        return (
            f"postgresql+asyncpg://{self.postgres_app_user}:{self.postgres_app_password}"
            f"@{self.postgres_host}:{self.postgres_port}/{self.postgres_db}"
        )

    # Redis
    redis_url: str = "redis://localhost:6379/0"

    # Demo tenant
    default_tenant_id: UUID = UUID("00000000-0000-0000-0000-000000000001")
    default_tenant_slug: str = "aegiscloud"

    # Source data
    transcript_data_path: str = ""

    # LLM
    llm_provider: str = "openai"
    llm_model: str = "gpt-4o-mini"
    llm_temperature: float = 0.0
    classifier_confidence_threshold: float = 0.7
    openai_api_key: str = ""
    anthropic_api_key: str = ""

    # JWT — must be set in .env for production; a random default is fine for dev
    jwt_secret: str = "change-me-in-production-use-a-32-char-random-string"

    # Langfuse — optional LLM observability (leave blank to disable)
    langfuse_public_key: str = ""
    langfuse_secret_key: str = ""
    langfuse_host: str = "https://cloud.langfuse.com"


settings = Settings()
