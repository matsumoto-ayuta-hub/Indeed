"""
Indeed Job Sync API クライアント。
GraphQL ベースの Job Sync API (2026年〜) を使って求人を投稿・更新・削除する。

認証: OAuth2 Client Credentials (2-legged)
エンドポイント: https://apis.indeed.com/graphql
"""
import time
import logging
from dataclasses import dataclass, field
from typing import Optional
from datetime import datetime, timezone
import httpx

from .config import settings, AccountConfig
from .models import Job, ProbationaryPeriod, SOCIAL_INSURANCE_SUIDS, WORK_SYSTEM_SUIDS

logger = logging.getLogger(__name__)

# ── GraphQL mutations ─────────────────────────────────────────────────────────

MUTATION_CREATE = """
mutation CreateJobPostings($input: CreateSourcedJobPostingsInput!) {
  jobsIngest {
    createSourcedJobPostings(input: $input) {
      results {
        jobPosting {
          sourcedPostingId
        }
        errors {
          field
          message
          type
        }
      }
    }
  }
}
"""

MUTATION_EXPIRE = """
mutation ExpireJobPosting($input: ExpireSourcedJobPostingInput!) {
  jobsIngest {
    expireSourcedJobPosting(input: $input) {
      jobPosting {
        sourcedPostingId
      }
      errors {
        field
        message
      }
    }
  }
}
"""

MUTATION_UPDATE = """
mutation UpdateJobPosting($input: UpdateSourcedJobPostingInput!) {
  jobsIngest {
    updateSourcedJobPosting(input: $input) {
      jobPosting {
        sourcedPostingId
      }
      errors {
        field
        message
      }
    }
  }
}
"""


@dataclass
class TokenCache:
    access_token: str = ""
    expires_at: float = 0.0

    def is_valid(self) -> bool:
        return bool(self.access_token) and time.time() < self.expires_at - 60


@dataclass
class SyncResult:
    success: bool
    indeed_posting_id: Optional[str] = None
    errors: list[dict] = field(default_factory=list)
    raw_response: Optional[dict] = None


class IndeedAPIClient:
    """Indeed Job Sync API (GraphQL) のクライアント。アカウントごとにインスタンスを作る。"""

    def __init__(self, account_config: AccountConfig):
        self.account = account_config
        self._token_cache = TokenCache()

    # ── 認証 ─────────────────────────────────────────────────────────────────

    def _get_access_token(self) -> str:
        if self._token_cache.is_valid():
            return self._token_cache.access_token

        resp = httpx.post(
            settings.indeed_token_url,
            data={
                "grant_type": "client_credentials",
                "client_id": self.account.client_id,
                "client_secret": self.account.client_secret,
            },
            headers={"Content-Type": "application/x-www-form-urlencoded"},
            timeout=10,
        )
        resp.raise_for_status()
        data = resp.json()
        self._token_cache.access_token = data["access_token"]
        self._token_cache.expires_at = time.time() + data.get("expires_in", 3600)
        logger.debug(f"[{self.account.id}] トークン取得成功")
        return self._token_cache.access_token

    def _graphql(self, query: str, variables: dict) -> dict:
        token = self._get_access_token()
        resp = httpx.post(
            settings.indeed_graphql_url,
            json={"query": query, "variables": variables},
            headers={
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/json",
            },
            timeout=30,
        )
        resp.raise_for_status()
        return resp.json()

    # ── 求人データ変換 ────────────────────────────────────────────────────────

    def _build_description_html(self, job: Job) -> str:
        """Indeed Japan が要求する HTML セグメント形式の説明文を組み立てる"""
        desc = job.description_modified or job.description
        html = f"<div>{desc}</div>"

        if job.working_hours:
            html += f'<div data-segment-label="WorkHours"><p>{job.working_hours}</p></div>'
        if job.holidays:
            html += f'<div data-segment-label="Holidays"><p>{job.holidays}</p></div>'
        if job.requirements:
            html += f'<div data-segment-label="Requirements"><p>{job.requirements}</p></div>'
        if job.benefits:
            html += f'<div data-segment-label="Benefits"><p>{job.benefits}</p></div>'

        # 有料職業紹介事業者として必須の注記
        html += (
            f'<div data-segment-label="AgencyInfo">'
            f'<p>【採用代行】{settings.agency_name}（有料職業紹介事業 許可番号：{settings.agency_license_number}）</p>'
            f'</div>'
        )
        return html

    def _build_location(self, job: Job) -> dict:
        """Indeed Japan 向けの location オブジェクトを構築する"""
        if job.is_remote and job.remote_type == "remote":
            return {"country": "JP", "streetAddress": ""}

        postal = job.postal_code or ""
        if postal and "-" not in postal and len(postal) == 7:
            postal = f"{postal[:3]}-{postal[3:]}"

        # streetAddress: 〒郵便番号 都道府県市区町村番地 の形式が必須
        parts = []
        if postal:
            parts.append(f"〒{postal}")
        if job.prefecture:
            parts.append(job.prefecture)
        if job.city:
            parts.append(job.city)
        if job.address:
            parts.append(job.address)

        return {
            "country": "JP",
            "streetAddress": " ".join(parts),
        }

    def _build_job_type_list(self, job: Job) -> list[str]:
        mapping = {
            "fulltime": ["FULL_TIME"],
            "parttime": ["PART_TIME"],
            "contract": ["THIRD_PARTY_CONTRACT"],
            "temporary": ["THIRD_PARTY_CONTRACT"],
            "internship": ["INTERNSHIP"],
            "freelance": ["CONTRACTOR"],
        }
        jt = job.job_type.value if hasattr(job.job_type, "value") else job.job_type
        return mapping.get(jt, ["FULL_TIME"])

    def _build_salary(self, job: Job) -> Optional[dict]:
        if not job.salary_min and not job.salary_description:
            return None
        period_map = {"monthly": "MONTHLY", "hourly": "HOURLY", "annual": "YEARLY"}
        period = period_map.get(job.salary_type or "monthly", "MONTHLY")
        salary: dict = {"currency": "JPY", "baseSalaryPeriod": period}
        if job.salary_min:
            salary["minBaseSalary"] = job.salary_min
        if job.salary_max:
            salary["maxBaseSalary"] = job.salary_max
        return salary

    def _build_attributes(self, job: Job) -> list[dict]:
        """社会保険・就業形態の SUIDs を構築する。未設定時は正社員向けデフォルトを付与。"""
        suids: list[str] = []

        si = job.social_insurance_suids or []
        ws = job.work_system_suids or []

        # 社会保険が未設定の場合、雇用形態に応じてデフォルトを設定
        if not si:
            jt = job.job_type.value if hasattr(job.job_type, "value") else job.job_type
            if jt in ("fulltime", "contract", "temporary"):
                si = list(SOCIAL_INSURANCE_SUIDS.values())
            elif jt in ("parttime", "internship"):
                si = [SOCIAL_INSURANCE_SUIDS["employment"], SOCIAL_INSURANCE_SUIDS["workers_comp"]]

        # 就業形態が未設定の場合、標準を設定
        if not ws:
            ws = [WORK_SYSTEM_SUIDS["standard"]]

        suids = si + ws
        return [{"suid": s} for s in suids]

    def _build_posting_input(self, job: Job) -> dict:
        hp = job.has_probationary_period
        if hasattr(hp, "value"):
            hp = hp.value
        if not hp or hp == "UNKNOWN":
            # Indeed Japan は UNKNOWN だと審査落ちするのでデフォルト YES にする
            hp = "YES"

        posting: dict = {
            "body": {
                "title": job.title,
                "description": self._build_description_html(job),
                "location": self._build_location(job),
                "jobTypes": self._build_job_type_list(job),
                "hasProbationaryPeriod": hp,
                "attributes": self._build_attributes(job),
            },
            "metadata": {
                "jobSource": {
                    "companyName": job.company_name,
                    "sourceName": self.account.publisher_name,
                    "sourceType": "ThirdPartyRecruiter",
                },
                "jobPostingId": job.job_reference_number or job.id,
                "datePublished": (job.published_at or datetime.utcnow()).replace(
                    tzinfo=timezone.utc
                ).isoformat(),
                "url": job.apply_url or f"{settings.app_base_url}/apply/{job.id}",
            },
        }

        if job.expires_at:
            posting["metadata"]["expirationDate"] = job.expires_at.replace(
                tzinfo=timezone.utc
            ).isoformat()

        salary = self._build_salary(job)
        if salary:
            posting["body"]["salary"] = salary

        if job.is_remote and job.remote_type in ("remote", "hybrid"):
            posting["body"]["remoteType"] = job.remote_type.upper()

        if job.probationary_period_months:
            posting["body"]["probationaryPeriodMonths"] = job.probationary_period_months

        return posting

    # ── 公開 API ──────────────────────────────────────────────────────────────

    def create_job(self, job: Job) -> SyncResult:
        if not self.account.has_credentials:
            return SyncResult(
                success=False,
                errors=[{"message": f"[{self.account.id}] OAuth クレデンシャルが未設定です。.env を確認してください。"}],
            )
        try:
            posting_input = self._build_posting_input(job)
            resp = self._graphql(MUTATION_CREATE, {"input": {"jobPostings": [posting_input]}})

            if "errors" in resp:
                return SyncResult(success=False, errors=resp["errors"], raw_response=resp)

            result = resp["data"]["jobsIngest"]["createSourcedJobPostings"]["results"][0]
            api_errors = result.get("errors") or []
            if api_errors:
                return SyncResult(success=False, errors=api_errors, raw_response=resp)

            posting_id = result["jobPosting"]["sourcedPostingId"]
            return SyncResult(success=True, indeed_posting_id=posting_id, raw_response=resp)

        except httpx.HTTPStatusError as e:
            return SyncResult(success=False, errors=[{"message": f"HTTP {e.response.status_code}: {e.response.text}"}])
        except Exception as e:
            return SyncResult(success=False, errors=[{"message": str(e)}])

    def expire_job(self, indeed_posting_id: str) -> SyncResult:
        if not self.account.has_credentials:
            return SyncResult(success=False, errors=[{"message": "クレデンシャル未設定"}])
        try:
            resp = self._graphql(
                MUTATION_EXPIRE,
                {"input": {"sourcedPostingId": indeed_posting_id}},
            )
            if "errors" in resp:
                return SyncResult(success=False, errors=resp["errors"], raw_response=resp)
            result = resp["data"]["jobsIngest"]["expireSourcedJobPosting"]
            api_errors = result.get("errors") or []
            if api_errors:
                return SyncResult(success=False, errors=api_errors, raw_response=resp)
            return SyncResult(success=True, indeed_posting_id=indeed_posting_id, raw_response=resp)
        except Exception as e:
            return SyncResult(success=False, errors=[{"message": str(e)}])

    def update_job(self, job: Job, indeed_posting_id: str) -> SyncResult:
        if not self.account.has_credentials:
            return SyncResult(success=False, errors=[{"message": "クレデンシャル未設定"}])
        try:
            posting_input = self._build_posting_input(job)
            posting_input["sourcedPostingId"] = indeed_posting_id
            resp = self._graphql(MUTATION_UPDATE, {"input": posting_input})
            if "errors" in resp:
                return SyncResult(success=False, errors=resp["errors"], raw_response=resp)
            result = resp["data"]["jobsIngest"]["updateSourcedJobPosting"]
            api_errors = result.get("errors") or []
            if api_errors:
                return SyncResult(success=False, errors=api_errors, raw_response=resp)
            return SyncResult(success=True, indeed_posting_id=indeed_posting_id, raw_response=resp)
        except Exception as e:
            return SyncResult(success=False, errors=[{"message": str(e)}])


# アカウントごとのシングルトンクライアントキャッシュ
_clients: dict[str, IndeedAPIClient] = {}


def get_client(account_id: str) -> IndeedAPIClient:
    from .config import ACCOUNT_CONFIG
    if account_id not in _clients:
        _clients[account_id] = IndeedAPIClient(ACCOUNT_CONFIG[account_id])
    return _clients[account_id]
