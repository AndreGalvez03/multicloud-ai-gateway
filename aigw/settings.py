"""Runtime settings.

Local defaults are fixture identifiers so `make up` works with no cloud account.
Production overrides them from the environment. See docs in the README for how
those values are injected (IAM roles, Secrets Manager, External Secrets).
"""

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="AIGW_",
        env_file=".env",
        extra="ignore",
    )

    database_url: str = "sqlite:///./aigw-local.db"
    litellm_base_url: str = "http://127.0.0.1:4000"
    litellm_api_key: str = "local-dev-master-key"
    admin_token: str = "local-admin-token"
    env: str = "local"
    allow_open_reads: bool = True
    seed_demo_data: bool = True
    embedding_dim: int = 64
    request_timeout_seconds: float = 30.0
    rate_window_seconds: int = 60


def get_settings() -> Settings:
    return Settings()
