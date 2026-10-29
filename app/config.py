from functools import lru_cache

from pathlib import Path

from typing import Literal


 

from pydantic import Field, SecretStr

from pydantic_settings import BaseSettings, SettingsConfigDict



 

class Settings(BaseSettings):

    warehouse_database_url: str

    app_database_url: str

    langgraph_checkpoint_database_url: str | None = None


 

    openai_api_key: SecretStr

    openai_analyst_model: str = "gpt-5.4-mini"

    openai_reasoning_effort: Literal["none", "low", "medium", "high", "xhigh"] = (

        "medium"

    )

    openai_timeout_seconds: int = Field(default=90, ge=10, le=600)

    openai_max_retries: int = Field(default=2, ge=0, le=5)


 

    sql_policy_path: Path = Path("config/sql_policy.yml")

    metrics_catalog_path: Path = Path("config/metrics.yml")

    dimensions_catalog_path: Path = Path("config/dimensions.yml")

    business_terms_path: Path = Path("config/business_terms.yml")

    prompts_directory: Path = Path("app/agents/prompts")


 

    warehouse_expected_user: str = "queryguard_reader"

    app_expected_user: str = "queryguard_app"


 

    warehouse_pool_min_size: int = Field(default=1, ge=0)

    warehouse_pool_max_size: int = Field(default=5, ge=1)

    app_pool_min_size: int = Field(default=1, ge=0)

    app_pool_max_size: int = Field(default=5, ge=1)


 

    database_connect_timeout_seconds: int = Field(default=5, ge=1, le=60)

    pool_wait_timeout_seconds: int = Field(default=10, ge=1, le=120)

    max_sql_repair_attempts: int = Field(default=2, ge=0, le=5)


 

    enable_query_execution_api: bool = True

    enable_analysis_api: bool = True


 

    model_config = SettingsConfigDict(

        env_file=".env",

        env_file_encoding="utf-8",

        extra="ignore",

        case_sensitive=False,

    )


 

    @property

    def checkpoint_database_url(self) -> str:

        return self.langgraph_checkpoint_database_url or self.app_database_url



 

@lru_cache

def get_settings() -> Settings:

    return Settings()


 