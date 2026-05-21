from pydantic_settings import BaseSettings
from pydantic import Field
from typing import Literal


class Settings(BaseSettings):
    anthropic_api_key: str = Field(..., env="ANTHROPIC_API_KEY")
    app_base_url: str = Field("http://localhost:8000", env="APP_BASE_URL")
    app_port: int = Field(8000, env="APP_PORT")
    secret_key: str = Field("change-me", env="SECRET_KEY")

    database_url: str = Field("sqlite:///./data/indeed_jobs.db", env="DATABASE_URL")

    agency_license_number: str = Field(..., env="AGENCY_LICENSE_NUMBER")
    agency_name: str = Field("株式会社キャリアジャパン", env="AGENCY_NAME")

    account1_id: str = Field("account_self", env="ACCOUNT1_ID")
    account1_publisher_name: str = Field("自社採用", env="ACCOUNT1_PUBLISHER_NAME")

    account2_id: str = Field("account_intern", env="ACCOUNT2_ID")
    account2_publisher_name: str = Field("インターン採用", env="ACCOUNT2_PUBLISHER_NAME")

    account3_id: str = Field("account_partner", env="ACCOUNT3_ID")
    account3_publisher_name: str = Field("パートナー採用", env="ACCOUNT3_PUBLISHER_NAME")

    feed_refresh_interval_hours: int = Field(6, env="FEED_REFRESH_INTERVAL_HOURS")
    job_expiry_days: int = Field(30, env="JOB_EXPIRY_DAYS")
    auto_renew_days_before_expiry: int = Field(5, env="AUTO_RENEW_DAYS_BEFORE_EXPIRY")

    claude_model: str = "claude-sonnet-4-6"

    class Config:
        env_file = ".env"
        extra = "ignore"


settings = Settings()

ACCOUNT_IDS = [
    settings.account1_id,
    settings.account2_id,
    settings.account3_id,
]

AccountId = Literal["account_self", "account_intern", "account_partner"]

ACCOUNT_CONFIG = {
    settings.account1_id: {
        "name": settings.account1_publisher_name,
        "allow_partner_jobs": True,
        "allow_own_jobs": True,
        "max_jobs": 500,
        "description": "自社採用 + 提携先一部掲載",
    },
    settings.account2_id: {
        "name": settings.account2_publisher_name,
        "allow_partner_jobs": False,
        "allow_own_jobs": True,
        "max_jobs": 50,
        "description": "インターン・アルバイト等の小規模採用",
        "allowed_job_types": ["internship", "parttime"],
    },
    settings.account3_id: {
        "name": settings.account3_publisher_name,
        "allow_partner_jobs": True,
        "allow_own_jobs": False,
        "max_jobs": 5000,
        "description": "提携先企業専用（大規模掲載）",
    },
}
