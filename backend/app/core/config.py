from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

PROJECT_ROOT = Path(__file__).resolve().parents[3]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=PROJECT_ROOT / ".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    postgres_db: str = "insighthub"
    postgres_user: str = "insighthub"
    postgres_password: str = ""
    database_url: str = "postgresql+psycopg://insighthub@127.0.0.1:5434/insighthub"
    redis_url: str = "redis://127.0.0.1:6380/0"
    insighthub_api_host: str = "127.0.0.1"
    insighthub_api_port: int = 8090
    max_upload_size_bytes: int = 104_857_600
    raw_storage_subdir: str = "data/raw"
    extracted_storage_subdir: str = "data/extracted"
    extraction_inline: bool = False
    web_fetch_timeout_seconds: float = 20
    web_fetch_max_bytes: int = 5_000_000
    web_fetch_max_redirects: int = 5
    web_browser_fallback_enabled: bool = True
    web_browser_timeout_seconds: float = 25
    web_browser_settle_ms: int = 800
    max_pdf_pages: int = 50
    chunk_max_chars: int = 2000
    chunk_overlap_chars: int = 200
    search_provider: str = "duckduckgo"
    search_http_endpoint: str = ""
    search_http_api_key: str = ""
    discovery_inline: bool = False
    llm_default_provider: str = ""
    llm_enable_fake: bool = False
    llm_test_legacy_providers: bool = False
    lmstudio_base_url: str = "http://127.0.0.1:1234/v1"
    lmstudio_model: str = ""
    deepseek_base_url: str = ""
    deepseek_api_key: str = ""
    deepseek_model: str = ""
    siliconflow_base_url: str = ""
    siliconflow_api_key: str = ""
    siliconflow_model: str = ""
    zai_base_url: str = "https://open.bigmodel.cn/api/paas/v4"
    zai_api_key: str = ""
    zai_model: str = "glm-5.3-flash"
    zai_file_parser_enabled: bool = False
    generic_llm_base_url: str = ""
    generic_llm_api_key: str = ""
    generic_llm_model: str = ""
    llm_timeout_seconds: float = 60
    llm_max_retries: int = 2
    analysis_max_output_tokens: int = 6000
    default_llm_context_window: int = 8000
    local_llm_context_window: int = 32768
    analysis_output_language: str = "auto"
    max_evidence_quote_chars: int = 500
    analysis_inline: bool = False
    analysis_job_timeout_seconds: int = 600
    pipeline_auto_analysis_enabled: bool = True
    category_assignment_threshold: float = 0.7
    embedding_enable_fake: bool = False
    embedding_dimensions: int = 1024
    embedding_batch_size: int = 16
    local_embedding_base_url: str = "http://127.0.0.1:1234/v1"
    local_embedding_model: str = ""
    generic_embedding_base_url: str = ""
    generic_embedding_api_key: str = ""
    generic_embedding_model: str = ""
    siliconflow_embedding_base_url: str = ""
    siliconflow_embedding_api_key: str = ""
    siliconflow_embedding_model: str = ""
    lexical_top_k: int = 30
    vector_top_k: int = 30
    hybrid_top_k: int = 20
    rrf_k: int = 60
    max_chunks_per_source: int = 4
    trigram_min_similarity: float = 0.12
    vector_max_distance: float = 0.45
    ask_max_coverage_sources: int = 10
    ask_coverage_slots: int = 8
    ask_history_turns: int = 2
    ask_inline: bool = False
    ask_streaming_enabled: bool = True
    ask_stream_ttl_seconds: int = 3600
    brief_inline: bool = False
    synthesis_batch_size: int = 4
    job_stale_after_seconds: int = 900
    disk_low_warning_bytes: int = 1_073_741_824
    llm_provider_fallback_enabled: bool = False
    minimax_base_url: str = "https://api.minimax.cn"
    minimax_api_key: str = ""
    minimax_image_model: str = "image-01"
    minimax_enable_fake: bool = False
    cover_storage_subdir: str = "data/covers"
    cover_inline: bool = False
    cover_max_bytes: int = 2_000_000
    cover_auto_enabled: bool = False
    cover_auto_requires_analysis: bool = True
    cover_monthly_budget: int = 100
    cover_auto_startup_scan_enabled: bool = True
    llm_fallback_provider: str = ""
    backup_postgres_container: str = "insighthub-postgres"
    insighthub_system_scope: str = "USER"
    insighthub_app_timezone: str = "Asia/Shanghai"

    def raw_storage_path(self) -> Path:
        return self._inside_project(self.raw_storage_subdir)

    def extracted_storage_path(self) -> Path:
        return self._inside_project(self.extracted_storage_subdir)

    def _inside_project(self, relative: str) -> Path:
        path = (PROJECT_ROOT / relative).resolve()
        root = PROJECT_ROOT.resolve()
        if path != root and root not in path.parents:
            raise RuntimeError("storage path must stay inside the project")
        return path


@lru_cache
def get_settings() -> Settings:
    return Settings()
