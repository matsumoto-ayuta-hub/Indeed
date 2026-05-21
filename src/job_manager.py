"""求人の作成・更新・Indeed API 同期・有効期限管理"""
import uuid
import logging
from datetime import datetime, timedelta
from typing import Optional

from sqlalchemy.orm import Session

from .config import settings, ACCOUNT_CONFIG
from .models import (
    Job, JobStatus, ComplianceStatus, ComplianceLog,
    JobCreate, ProbationaryPeriod,
)
from .compliance import ComplianceChecker
from .indeed_api import get_client, SyncResult

logger = logging.getLogger(__name__)


class JobManager:
    def __init__(self, db: Session):
        self.db = db
        self.checker = ComplianceChecker()

    # ── 求人 CRUD ─────────────────────────────────────────────────────────────

    def create_job(self, data: JobCreate, auto_check: bool = True) -> Job:
        job = Job(
            id=str(uuid.uuid4()),
            job_reference_number=f"CJ-{uuid.uuid4().hex[:8].upper()}",
            account_ids=data.account_ids,
            title=data.title,
            company_name=data.company_name,
            is_partner_company=data.is_partner_company,
            partner_company_id=data.partner_company_id,
            postal_code=data.postal_code,
            prefecture=data.prefecture,
            city=data.city,
            address=data.address,
            is_remote=data.is_remote,
            remote_type=data.remote_type,
            job_type=data.job_type,
            salary_min=data.salary_min,
            salary_max=data.salary_max,
            salary_type=data.salary_type,
            salary_description=data.salary_description,
            working_hours=data.working_hours,
            holidays=data.holidays,
            benefits=data.benefits,
            requirements=data.requirements,
            description=data.description,
            apply_url=data.apply_url,
            category=data.category,
            keywords=data.keywords,
            source_url=data.source_url,
            source_platform=data.source_platform,
            is_republishable=data.is_republishable,
            republish_permission=data.republish_permission,
            has_probationary_period=data.has_probationary_period,
            probationary_period_months=data.probationary_period_months,
            social_insurance_suids=data.social_insurance_suids,
            work_system_suids=data.work_system_suids,
            status=JobStatus.PENDING_REVIEW,
            indeed_posting_ids={},
            last_sync_at={},
            sync_errors={},
        )
        self.db.add(job)
        self.db.flush()

        if auto_check:
            self._run_compliance(job)

        self.db.commit()
        return job

    def update_job(self, job_id: str, data: dict, recheck: bool = True) -> Optional[Job]:
        job = self.db.query(Job).filter(Job.id == job_id).first()
        if not job:
            return None
        for k, v in data.items():
            if hasattr(job, k):
                setattr(job, k, v)
        job.updated_at = datetime.utcnow()
        if recheck:
            job.compliance_status = ComplianceStatus.UNCHECKED
            self._run_compliance(job)
        self.db.commit()
        return job

    def get_jobs(
        self,
        account_id: Optional[str] = None,
        status: Optional[JobStatus] = None,
        limit: int = 100,
    ) -> list[Job]:
        q = self.db.query(Job)
        if status:
            q = q.filter(Job.status == status)
        jobs = q.limit(limit).all()
        if account_id:
            jobs = [j for j in jobs if account_id in (j.account_ids or [])]
        return jobs

    # ── コンプライアンスチェック ──────────────────────────────────────────────

    def _run_compliance(self, job: Job):
        result = self.checker.check(job)
        log = ComplianceLog(
            job_id=job.id,
            status=result.status,
            issues_found=result.issues,
            fixes_applied=[i for i in result.issues if i.get("fix_suggestion")],
            original_description=job.description_modified or job.description,
            modified_description=result.modified_description,
            model_used=result.model_used,
            tokens_used=result.tokens_used,
        )
        self.db.add(log)
        job.compliance_status = result.status
        job.compliance_notes = result.issues
        if result.modified_description:
            job.description_modified = result.modified_description
        if result.status in (ComplianceStatus.COMPLIANT, ComplianceStatus.FIXED):
            if job.status == JobStatus.PENDING_REVIEW:
                job.status = JobStatus.PENDING_REVIEW  # publish() で ACTIVE にする
        elif result.status == ComplianceStatus.FAILED:
            job.status = JobStatus.REJECTED

    # ── Indeed API 同期 ───────────────────────────────────────────────────────

    def publish(self, job_id: str) -> Optional[Job]:
        """コンプライアンス済みの求人を Indeed API に投稿して ACTIVE にする"""
        job = self.db.query(Job).filter(Job.id == job_id).first()
        if not job:
            return None
        if job.compliance_status not in (ComplianceStatus.COMPLIANT, ComplianceStatus.FIXED):
            raise ValueError("コンプライアンスチェックが未完了です。/api/jobs/{id}/check を実行してください。")

        now = datetime.utcnow()
        job.published_at = now
        job.expires_at = now + timedelta(days=settings.job_expiry_days)

        self._sync_to_indeed(job)

        if any(v for v in (job.indeed_posting_ids or {}).values()):
            job.status = JobStatus.ACTIVE
        self.db.commit()
        return job

    def renew(self, job_id: str, recheck: bool = True) -> Optional[Job]:
        """期限延長 + Indeed API 上の求人を更新"""
        job = self.db.query(Job).filter(Job.id == job_id).first()
        if not job:
            return None
        if recheck:
            self._run_compliance(job)
        if job.compliance_status not in (ComplianceStatus.COMPLIANT, ComplianceStatus.FIXED):
            logger.warning(f"求人 {job_id} は再チェック後もコンプライアンス未通過のため更新スキップ")
            return job

        now = datetime.utcnow()
        job.expires_at = now + timedelta(days=settings.job_expiry_days)
        job.last_renewed_at = now
        self._sync_to_indeed(job)
        job.status = JobStatus.ACTIVE
        self.db.commit()
        return job

    def expire_job(self, job_id: str) -> Optional[Job]:
        """Indeed API 上の求人を取り下げてローカルを EXPIRED に更新"""
        job = self.db.query(Job).filter(Job.id == job_id).first()
        if not job:
            return None
        self._expire_on_indeed(job)
        job.status = JobStatus.EXPIRED
        self.db.commit()
        return job

    def expire_old_jobs(self) -> int:
        """有効期限切れの求人を一括取り下げ"""
        now = datetime.utcnow()
        expired = (
            self.db.query(Job)
            .filter(Job.status == JobStatus.ACTIVE, Job.expires_at < now)
            .all()
        )
        for job in expired:
            self._expire_on_indeed(job)
            job.status = JobStatus.EXPIRED
        self.db.commit()
        return len(expired)

    def auto_renew_expiring(self) -> list[str]:
        """期限が近い転載求人を自動リニュー"""
        threshold = datetime.utcnow() + timedelta(days=settings.auto_renew_days_before_expiry)
        expiring = (
            self.db.query(Job)
            .filter(
                Job.status == JobStatus.ACTIVE,
                Job.expires_at <= threshold,
                Job.is_republishable == True,
            )
            .all()
        )
        renewed = []
        for job in expiring:
            try:
                self.renew(job.id, recheck=True)
                renewed.append(job.id)
            except Exception as e:
                logger.error(f"自動更新失敗 {job.id}: {e}")
        return renewed

    def sync_all_active(self, account_id: Optional[str] = None) -> dict:
        """ACTIVE 求人をすべて Indeed API に同期（差分更新）"""
        from .models import SyncLog
        import time
        start = time.time()
        created = updated = error = 0
        errors = []

        q = self.db.query(Job).filter(Job.status == JobStatus.ACTIVE)
        jobs = q.all()

        for job in jobs:
            target_accounts = [a for a in (job.account_ids or []) if self._account_allows(job, a)]
            if account_id:
                target_accounts = [a for a in target_accounts if a == account_id]

            for acc_id in target_accounts:
                existing_id = (job.indeed_posting_ids or {}).get(acc_id)
                client = get_client(acc_id)

                if existing_id:
                    result = client.update_job(job, existing_id)
                    if result.success:
                        updated += 1
                    else:
                        error += 1
                        msg = f"{job.id}/{acc_id}: {result.errors}"
                        errors.append(msg)
                        logger.error(f"更新失敗: {msg}")
                else:
                    result = client.create_job(job)
                    if result.success:
                        created += 1
                        ids = dict(job.indeed_posting_ids or {})
                        ids[acc_id] = result.indeed_posting_id
                        job.indeed_posting_ids = ids
                        ts = dict(job.last_sync_at or {})
                        ts[acc_id] = datetime.utcnow().isoformat()
                        job.last_sync_at = ts
                    else:
                        error += 1
                        msg = f"{job.id}/{acc_id}: {result.errors}"
                        errors.append(msg)
                        errs = dict(job.sync_errors or {})
                        errs[acc_id] = str(result.errors)
                        job.sync_errors = errs
                        logger.error(f"投稿失敗: {msg}")

        self.db.commit()

        target_acc = account_id or "all"
        log = SyncLog(
            account_id=target_acc,
            created_count=created,
            updated_count=updated,
            error_count=error,
            errors=errors,
            duration_seconds=int(time.time() - start),
        )
        self.db.add(log)
        self.db.commit()

        return {"created": created, "updated": updated, "errors": error, "error_details": errors}

    # ── 内部ヘルパー ──────────────────────────────────────────────────────────

    def _sync_to_indeed(self, job: Job):
        for acc_id in (job.account_ids or []):
            if not self._account_allows(job, acc_id):
                continue
            client = get_client(acc_id)
            existing_id = (job.indeed_posting_ids or {}).get(acc_id)

            if existing_id:
                result = client.update_job(job, existing_id)
            else:
                result = client.create_job(job)

            ids = dict(job.indeed_posting_ids or {})
            ts = dict(job.last_sync_at or {})
            errs = dict(job.sync_errors or {})

            if result.success:
                if result.indeed_posting_id:
                    ids[acc_id] = result.indeed_posting_id
                ts[acc_id] = datetime.utcnow().isoformat()
                errs.pop(acc_id, None)
            else:
                errs[acc_id] = str(result.errors)
                logger.error(f"[{acc_id}] Indeed 同期失敗 job={job.id}: {result.errors}")

            job.indeed_posting_ids = ids
            job.last_sync_at = ts
            job.sync_errors = errs

    def _expire_on_indeed(self, job: Job):
        for acc_id, posting_id in (job.indeed_posting_ids or {}).items():
            if not posting_id:
                continue
            client = get_client(acc_id)
            result = client.expire_job(posting_id)
            if not result.success:
                logger.error(f"[{acc_id}] 取り下げ失敗 posting={posting_id}: {result.errors}")

    def _account_allows(self, job: Job, acc_id: str) -> bool:
        cfg = ACCOUNT_CONFIG.get(acc_id)
        if not cfg:
            return False
        if not cfg.allow_partner_jobs and job.is_partner_company:
            return False
        if not cfg.allow_own_jobs and not job.is_partner_company:
            return False
        if cfg.allowed_job_types:
            jt = job.job_type.value if hasattr(job.job_type, "value") else job.job_type
            if jt not in cfg.allowed_job_types:
                return False
        return True
