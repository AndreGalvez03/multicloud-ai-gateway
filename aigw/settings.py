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
    secrets_manager_secret: str = ""


_LOCAL_ENVS = {"local", "test"}
_DEFAULT_ADMIN = "local-admin-token"
_DEFAULT_LITELLM = "local-dev-master-key"


def get_settings() -> Settings:
    return load_runtime_secrets(Settings())


def load_runtime_secrets(settings: Settings) -> Settings:
    """Pull admin and provider material from Secrets Manager when configured.

    Local and test runs leave the fixture values in place. A non-local boot
    refuses those fixtures so a pod cannot start with the compose defaults.
    External Secrets can also inject the same variables; this loader is the
    in-process path when AIGW_SECRETS_MANAGER_SECRET is set.
    """
    if settings.secrets_manager_secret:
        settings = _from_secrets_manager(settings)
    if settings.env not in _LOCAL_ENVS:
        if settings.admin_token in {"", _DEFAULT_ADMIN} or settings.allow_open_reads:
            raise RuntimeError(
                "refusing to boot outside local: set AIGW_ADMIN_TOKEN from Secrets Manager "
                "or External Secrets, and set AIGW_ALLOW_OPEN_READS=false"
            )
        if settings.litellm_api_key in {"", _DEFAULT_LITELLM}:
            raise RuntimeError("refusing to boot outside local with the fixture LiteLLM key")
    return settings


def _from_secrets_manager(settings: Settings) -> Settings:
    import importlib
    import json

    try:
        boto3 = importlib.import_module("boto3")
    except ImportError as exc:
        raise RuntimeError("boto3 is required to read AIGW_SECRETS_MANAGER_SECRET") from exc
    client = boto3.client("secretsmanager")
    raw = client.get_secret_value(SecretId=settings.secrets_manager_secret)["SecretString"]
    payload = json.loads(raw)
    if not isinstance(payload, dict):
        raise RuntimeError("Secrets Manager value must be a JSON object")
    updates: dict[str, object] = {}
    for key in ("admin_token", "litellm_api_key", "database_url"):
        value = payload.get(key)
        if isinstance(value, str) and value:
            updates[key] = value
    return settings.model_copy(update=updates)
