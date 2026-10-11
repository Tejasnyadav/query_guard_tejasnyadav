from functools import lru_cache

from pathlib import Path


 

from pydantic import Field

from pydantic_settings import BaseSettings, SettingsConfigDict



 

class Settings(BaseSettings):

    warehouse_database_url: str

    app_database_url: str


 

    sql_policy_path: Path = Path("config/sql_policy.yml")

    warehouse_expected_user: str = "queryguard_reader"

    app_expected_user: str = "queryguard_app"


 

    warehouse_pool_min_size: int = Field(default=1, ge=0)

    warehouse_pool_max_size: int = Field(default=5, ge=1)

    app_pool_min_size: int = Field(default=1, ge=0)

    app_pool_max_size: int = Field(default=5, ge=1)


 

    database_connect_timeout_seconds: int = Field(default=5, ge=1, le=60)

    pool_wait_timeout_seconds: int = Field(default=10, ge=1, le=120)

    enable_query_execution_api: bool = True


 

    model_config = SettingsConfigDict(

        env_file=".env",

        env_file_encoding="utf-8",

        extra="ignore",

        case_sensitive=False,

    )



 

@lru_cache

def get_settings() -> Settings:

    return Settings()


 