"""Configuration management using pydantic-settings."""

from enum import StrEnum

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class NexusEnvironment(StrEnum):
    DEVELOPMENT = "development"
    TESTING = "testing"
    STAGING = "staging"
    PRODUCTION = "production"


class DatabaseSettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="POSTGRES_")

    host: str = "localhost"
    port: int = 5432
    user: str = "nexus"
    password: SecretStr = SecretStr("nexus_dev_password")
    db: str = "nexus"

    @property
    def async_url(self) -> str:
        return (
            f"postgresql+asyncpg://{self.user}:{self.password.get_secret_value()}"
            f"@{self.host}:{self.port}/{self.db}"
        )

    @property
    def sync_url(self) -> str:
        return (
            f"postgresql://{self.user}:{self.password.get_secret_value()}"
            f"@{self.host}:{self.port}/{self.db}"
        )


class RedisSettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="REDIS_")

    host: str = "localhost"
    port: int = 6379
    db: int = 0

    @property
    def url(self) -> str:
        return f"redis://{self.host}:{self.port}/{self.db}"


class LangfuseSettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="LANGFUSE_")

    public_key: SecretStr = SecretStr("")
    secret_key: SecretStr = SecretStr("")
    host: str = "https://cloud.langfuse.com"

    @property
    def enabled(self) -> bool:
        return bool(self.public_key.get_secret_value() and self.secret_key.get_secret_value())


class NexusSettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="NEXUS_", env_file=".env")

    env: NexusEnvironment = NexusEnvironment.DEVELOPMENT
    log_level: str = "DEBUG"
    secret_key: SecretStr = SecretStr("change-me-in-production")
    api_key: SecretStr = SecretStr("")

    database: DatabaseSettings = Field(default_factory=DatabaseSettings)
    redis: RedisSettings = Field(default_factory=RedisSettings)
    langfuse: LangfuseSettings = Field(default_factory=LangfuseSettings)


settings = NexusSettings()
