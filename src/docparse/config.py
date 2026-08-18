from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="DOCPARSE_",
        env_file=".env",
        extra="ignore",
    )

    llm_base_url: str = "https://api.openai.com/v1"
    llm_api_key: str = ""
    llm_model: str = "gpt-4.1-mini"
    vlm_model: str = "gpt-4.1-mini"

    job_store: str = "memory"
    file_store: str = "memory"

    max_upload_mb: int = 100
    max_archive_files: int = 200
    max_archive_depth: int = 3
    max_archive_ratio: int = 100
    max_uncompressed_mb: int = 500

    host: str = "127.0.0.1"
    port: int = 8088

    # 预留：真正落库时再启用
    database_url: str | None = None
    s3_bucket: str | None = None
    s3_endpoint: str | None = None

    app_name: str = Field(default="docparse")


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
