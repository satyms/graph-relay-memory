import os
from typing import Optional
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    falkordb_host: str = "localhost"
    falkordb_port: int = 6379
    admin_token: str = "relay-admin-secret-dev-token"
    model_provider: str = "anthropic"
    model: str = "claude-3-5-sonnet-20241022"
    anthropic_api_key: Optional[str] = None
    openvino_base_url: str = "http://localhost:8000/v1"
    server_port: int = 8080
    demo_mode: bool = True
    chaos_lease_seconds: int = 10

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore"
    )


settings = Settings()
