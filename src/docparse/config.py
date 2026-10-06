from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="DOCPARSE_",
        env_file=".env",
        extra="ignore",
    )

    # 云端外呼硬闸（#100）。默认 false：未显式启用时，下面的云 OCR（TextIn）与云
    # LLM 一律不构造请求、不发 HTTP——**配了密钥也不外发**。管的是「有没有显式开闸」，
    # 不看端点地址：内网端点（#101）同样要显式开闸。闸门实现在 adapters/cloud_gate.py。
    allow_cloud: bool = False

    llm_base_url: str = "https://api.openai.com/v1"
    llm_api_key: str = ""
    llm_model: str = "gpt-4.1-mini"
    vlm_model: str = "gpt-4.1-mini"

    # 扫描件 OCR 引擎选择（#99）。本地优先（#94）：默认 local，不出网。
    # local  = PaddleOCR PP-OCRv6 small + doc-ori 方向分类（#110 选型）
    # textin = 合合云通用 OCR（保留，需显式选；云侧硬闸见 #100）
    ocr_engine: str = "local"
    # 本地引擎设备：auto（有 CUDA 用 gpu，否则 cpu）/ cpu / gpu
    local_ocr_device: str = "auto"
    # CPU 上 PaddleOCR 的线程数；None 就用官方默认
    local_ocr_cpu_threads: int | None = None

    # 云 OCR（TextIn 通用，#60 选型）；无密钥时扫描件只登记告警，不崩
    textin_app_id: str = ""
    textin_secret_code: str = ""

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
