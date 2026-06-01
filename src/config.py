from pydantic_settings import BaseSettings
from pydantic import Field
from dataclasses import dataclass
from typing import Optional


class Settings(BaseSettings):
    anthropic_api_key: str = Field(..., env="ANTHROPIC_API_KEY")
    app_base_url: str = Field("http://localhost:8000", env="APP_BASE_URL")
    app_port: int = Field(8000, env="APP_PORT")
    secret_key: str = Field("change-me", env="SECRET_KEY")

    database_url: str = Field("sqlite:///./data/indeed_jobs.db", env="DATABASE_URL")

    agency_license_number: str = Field("13-ユ-318960", env="AGENCY_LICENSE_NUMBER")
    agency_name: str = Field("株式会社キャリアジャパン", env="AGENCY_NAME")

    # Indeed Partner Console OAuth credentials (per account)
    account_self_client_id: str = Field("", env="ACCOUNT_SELF_CLIENT_ID")
    account_self_client_secret: str = Field("", env="ACCOUNT_SELF_CLIENT_SECRET")
    account_self_publisher_name: str = Field("株式会社キャリアジャパン自社採用", env="ACCOUNT_SELF_PUBLISHER_NAME")

    account_intern_client_id: str = Field("", env="ACCOUNT_INTERN_CLIENT_ID")
    account_intern_client_secret: str = Field("", env="ACCOUNT_INTERN_CLIENT_SECRET")
    account_intern_publisher_name: str = Field("キャリアジャパンインターン採用", env="ACCOUNT_INTERN_PUBLISHER_NAME")

    account_partner_client_id: str = Field("", env="ACCOUNT_PARTNER_CLIENT_ID")
    account_partner_client_secret: str = Field("", env="ACCOUNT_PARTNER_CLIENT_SECRET")
    account_partner_publisher_name: str = Field("キャリアジャパンパートナー採用", env="ACCOUNT_PARTNER_PUBLISHER_NAME")

    # Indeed API endpoints
    indeed_token_url: str = Field("https://apis.indeed.com/oauth/v2/tokens", env="INDEED_TOKEN_URL")
    indeed_graphql_url: str = Field("https://apis.indeed.com/graphql", env="INDEED_GRAPHQL_URL")

    job_expiry_days: int = Field(30, env="JOB_EXPIRY_DAYS")
    auto_renew_days_before_expiry: int = Field(5, env="AUTO_RENEW_DAYS_BEFORE_EXPIRY")
    sync_interval_hours: int = Field(6, env="SYNC_INTERVAL_HOURS")

    # Slack批評ボット設定
    slack_bot_token: str = Field("", env="SLACK_BOT_TOKEN")
    slack_signing_secret: str = Field("", env="SLACK_SIGNING_SECRET")
    slack_critique_channel_id: str = Field("", env="SLACK_CRITIQUE_CHANNEL_ID")
    araki_ryuki_slack_user_id: str = Field("", env="ARAKI_RYUKI_SLACK_USER_ID")

    claude_model: str = "claude-sonnet-4-6"

    class Config:
        env_file = ".env"
        extra = "ignore"


settings = Settings()


@dataclass
class AccountConfig:
    id: str
    publisher_name: str
    client_id: str
    client_secret: str
    allow_partner_jobs: bool
    allow_own_jobs: bool
    max_jobs: int
    allowed_job_types: Optional[list]
    description: str

    @property
    def has_credentials(self) -> bool:
        return bool(self.client_id and self.client_secret)


ACCOUNT_CONFIG: dict[str, AccountConfig] = {
    "account_self": AccountConfig(
        id="account_self",
        publisher_name=settings.account_self_publisher_name,
        client_id=settings.account_self_client_id,
        client_secret=settings.account_self_client_secret,
        allow_partner_jobs=True,
        allow_own_jobs=True,
        max_jobs=500,
        allowed_job_types=None,
        description="自社採用 + 提携先一部掲載",
    ),
    "account_intern": AccountConfig(
        id="account_intern",
        publisher_name=settings.account_intern_publisher_name,
        client_id=settings.account_intern_client_id,
        client_secret=settings.account_intern_client_secret,
        allow_partner_jobs=False,
        allow_own_jobs=True,
        max_jobs=50,
        allowed_job_types=["internship", "parttime"],
        description="インターン・アルバイト等の小規模採用",
    ),
    "account_partner": AccountConfig(
        id="account_partner",
        publisher_name=settings.account_partner_publisher_name,
        client_id=settings.account_partner_client_id,
        client_secret=settings.account_partner_client_secret,
        allow_partner_jobs=True,
        allow_own_jobs=False,
        max_jobs=5000,
        allowed_job_types=None,
        description="提携先企業専用（大規模掲載）",
    ),
}

ACCOUNT_IDS = list(ACCOUNT_CONFIG.keys())
