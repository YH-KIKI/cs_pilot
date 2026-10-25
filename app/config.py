from functools import lru_cache
from pathlib import Path

from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

ROOT = Path(__file__).resolve().parent.parent


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=ROOT / ".env", extra="ignore")

    openai_api_key: SecretStr = SecretStr("")
    openai_model: str = "gpt-6-luna"
    openai_embedding_model: str = "text-embedding-3-small"
    orders_db_path: Path = ROOT / "data/runtime/orders.sqlite3"
    rag_allow_api: bool = False

    @property
    def db_path(self) -> Path:
        path = self.orders_db_path
        return path.resolve() if path.is_absolute() else (ROOT / path).resolve()


@lru_cache
def get_settings() -> Settings:
    return Settings()
