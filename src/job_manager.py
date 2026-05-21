"""求人の作成・更新・有効期限管理・自動更新処理"""
import uuid
from datetime import datetime, timedelta
from typing import Optional, List
from sqlalchemy.orm import Session

from .config import settings
from .models import Job, JobStatus, ComplianceStatus, ComplianceLog, JobCreate
from .compliance import ComplianceChecker


class JobManager:
    def __init__(self, db: Session):
        self.db = db
        self.checker = ComplianceChecker()

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
            status=JobStatus.PENDING_REVIEW,
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

    def publish(self, job_id: str) -> Optional[Job]:
        job = self.db.query(Job).filter(Job.id == job_id).first()
        if not job:
            return None
        if job.compliance_status not in (ComplianceStatus.COMPLIANT, ComplianceStatus.FIXED):
            raise ValueError(f"求人 {job_id} はコンプライアンスチェックが完了していません。")
        now = datetime.utcnow()
        job.status = JobStatus.ACTIVE
        job.published_at = now
        job.expires_at = now + timedelta(days=settings.job_expiry_days)
        self.db.commit()
        return job

    def renew(self, job_id: str, recheck: bool = True) -> Optional[Job]:
        """求人を更新（有効期限を延長）"""
        job = self.db.query(Job).filter(Job.id == job_id).first()
        if not job:
            return None
        if recheck:
            self._run_compliance(job)
        if job.compliance_status in (ComplianceStatus.COMPLIANT, ComplianceStatus.FIXED):
            now = datetime.utcnow()
            job.expires_at = now + timedelta(days=settings.job_expiry_days)
            job.last_renewed_at = now
            job.status = JobStatus.ACTIVE
        self.db.commit()
        return job

    def expire_old_jobs(self) -> int:
        """有効期限切れの求人をステータス更新"""
        now = datetime.utcnow()
        expired = (
            self.db.query(Job)
            .filter(Job.status == JobStatus.ACTIVE, Job.expires_at < now)
            .all()
        )
        for job in expired:
            job.status = JobStatus.EXPIRED
        self.db.commit()
        return len(expired)

    def auto_renew_expiring(self) -> List[str]:
        """期限が近い求人を自動更新"""
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
                self.renew(job.id)
                renewed.append(job.id)
            except Exception as e:
                print(f"Auto-renew failed for {job.id}: {e}")
        return renewed

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
            job.status = JobStatus.ACTIVE if job.status == JobStatus.PENDING_REVIEW else job.status
        elif result.status == ComplianceStatus.FAILED:
            job.status = JobStatus.REJECTED

    def get_jobs(
        self,
        account_id: Optional[str] = None,
        status: Optional[JobStatus] = None,
        limit: int = 100,
    ) -> List[Job]:
        q = self.db.query(Job)
        if status:
            q = q.filter(Job.status == status)
        jobs = q.limit(limit).all()
        if account_id:
            jobs = [j for j in jobs if account_id in (j.account_ids or [])]
        return jobs
