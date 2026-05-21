from datetime import datetime
from enum import Enum
from typing import Optional, List
from sqlalchemy import (
    Column, String, Text, DateTime, Boolean, Integer,
    ForeignKey, JSON, Enum as SAEnum, Index
)
from sqlalchemy.orm import relationship, DeclarativeBase
from pydantic import BaseModel, Field


class Base(DeclarativeBase):
    pass


class JobType(str, Enum):
    FULLTIME = "fulltime"
    PARTTIME = "parttime"
    CONTRACT = "contract"
    TEMPORARY = "temporary"
    INTERNSHIP = "internship"
    FREELANCE = "freelance"


class JobStatus(str, Enum):
    DRAFT = "draft"
    PENDING_REVIEW = "pending_review"
    ACTIVE = "active"
    SUSPENDED = "suspended"
    EXPIRED = "expired"
    REJECTED = "rejected"


class ComplianceStatus(str, Enum):
    UNCHECKED = "unchecked"
    COMPLIANT = "compliant"
    FIXED = "fixed"
    NEEDS_MANUAL_REVIEW = "needs_manual_review"
    FAILED = "failed"


class ProbationaryPeriod(str, Enum):
    YES = "YES"
    NO = "NO"
    UNKNOWN = "UNKNOWN"


# Indeed Japan 社会保険 SUID
SOCIAL_INSURANCE_SUIDS = {
    "health": "SOCIAL_INSURANCE_HEALTH",           # 健康保険
    "pension": "SOCIAL_INSURANCE_EMPLOYEES_PENSION", # 厚生年金
    "employment": "SOCIAL_INSURANCE_EMPLOYMENT",    # 雇用保険
    "workers_comp": "SOCIAL_INSURANCE_WORKERS_COMP", # 労災保険
}

# Indeed Japan 就業形態 SUID
WORK_SYSTEM_SUIDS = {
    "standard": "WORK_SYSTEM_STANDARD",             # 固定時間制
    "flex": "WORK_SYSTEM_FLEX",                     # フレックスタイム制
    "discretionary_professional": "WORK_SYSTEM_DISCRETIONARY_PROFESSIONAL",  # 専門業務裁量労働制
    "discretionary_planning": "WORK_SYSTEM_DISCRETIONARY_PLANNING",           # 企画業務裁量労働制
    "shift": "WORK_SYSTEM_SHIFT",                   # シフト制
}


class Job(Base):
    __tablename__ = "jobs"

    id = Column(String(36), primary_key=True)
    account_ids = Column(JSON, nullable=False)

    # 求人基本情報
    title = Column(String(255), nullable=False)
    company_name = Column(String(255), nullable=False)
    is_partner_company = Column(Boolean, default=False)
    partner_company_id = Column(String(36), ForeignKey("partner_companies.id"), nullable=True)

    # 勤務地
    postal_code = Column(String(10))
    prefecture = Column(String(50))
    city = Column(String(100))
    address = Column(String(255))
    is_remote = Column(Boolean, default=False)
    remote_type = Column(String(20))  # "onsite" | "remote" | "hybrid"

    # 雇用条件
    job_type = Column(SAEnum(JobType), nullable=False)
    salary_min = Column(Integer)
    salary_max = Column(Integer)
    salary_type = Column(String(20))  # "monthly" | "hourly" | "annual"
    salary_description = Column(String(500))
    working_hours = Column(String(500))
    holidays = Column(String(500))
    benefits = Column(Text)
    requirements = Column(Text)

    # 求人内容
    description = Column(Text, nullable=False)
    description_modified = Column(Text)  # コンプライアンス修正後

    # Indeed Japan 必須フィールド
    has_probationary_period = Column(SAEnum(ProbationaryPeriod), default=ProbationaryPeriod.UNKNOWN)
    probationary_period_months = Column(Integer)
    social_insurance_suids = Column(JSON)   # 適用社会保険のSUIDリスト
    work_system_suids = Column(JSON)        # 就業形態SUIDs

    # 応募URL
    apply_url = Column(String(500))
    job_reference_number = Column(String(100), unique=True)

    # カテゴリ・タグ
    category = Column(String(100))
    keywords = Column(JSON)

    # ステータス管理
    status = Column(SAEnum(JobStatus), default=JobStatus.DRAFT)
    compliance_status = Column(SAEnum(ComplianceStatus), default=ComplianceStatus.UNCHECKED)
    compliance_notes = Column(JSON)

    # Indeed API から返された識別子（アカウントIDをキーにした辞書）
    indeed_posting_ids = Column(JSON, default=dict)  # {"account_self": "indeed_id_xxx", ...}
    last_sync_at = Column(JSON, default=dict)         # {"account_self": "2026-05-21T...", ...}
    sync_errors = Column(JSON, default=dict)          # {"account_self": "error msg", ...}

    # 日付管理
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    published_at = Column(DateTime)
    expires_at = Column(DateTime)
    last_renewed_at = Column(DateTime)
    source_updated_at = Column(DateTime)

    # 転載情報
    source_url = Column(String(500))
    source_platform = Column(String(100))
    is_republishable = Column(Boolean, default=False)
    republish_permission = Column(String(100))

    partner_company = relationship("PartnerCompany", back_populates="jobs")
    compliance_logs = relationship(
        "ComplianceLog", back_populates="job",
        order_by="ComplianceLog.checked_at.desc()"
    )

    __table_args__ = (
        Index("ix_jobs_status", "status"),
        Index("ix_jobs_expires_at", "expires_at"),
        Index("ix_jobs_company", "company_name"),
    )


class PartnerCompany(Base):
    __tablename__ = "partner_companies"

    id = Column(String(36), primary_key=True)
    name = Column(String(255), nullable=False, unique=True)
    name_kana = Column(String(255))
    prefecture = Column(String(50))
    industry = Column(String(100))
    contact_person = Column(String(100))
    contract_type = Column(String(50))       # "full_partner" | "referral" | "listing_only"
    allowed_accounts = Column(JSON)
    is_active = Column(Boolean, default=True)
    notes = Column(Text)
    created_at = Column(DateTime, default=datetime.utcnow)

    jobs = relationship("Job", back_populates="partner_company")


class ComplianceLog(Base):
    __tablename__ = "compliance_logs"

    id = Column(Integer, primary_key=True, autoincrement=True)
    job_id = Column(String(36), ForeignKey("jobs.id"), nullable=False)
    checked_at = Column(DateTime, default=datetime.utcnow)
    status = Column(SAEnum(ComplianceStatus))
    issues_found = Column(JSON)
    fixes_applied = Column(JSON)
    original_description = Column(Text)
    modified_description = Column(Text)
    model_used = Column(String(100))
    tokens_used = Column(Integer)

    job = relationship("Job", back_populates="compliance_logs")


class SyncLog(Base):
    __tablename__ = "sync_logs"

    id = Column(Integer, primary_key=True, autoincrement=True)
    account_id = Column(String(100), nullable=False)
    synced_at = Column(DateTime, default=datetime.utcnow)
    created_count = Column(Integer, default=0)
    updated_count = Column(Integer, default=0)
    expired_count = Column(Integer, default=0)
    error_count = Column(Integer, default=0)
    errors = Column(JSON)
    duration_seconds = Column(Integer)


# ── Pydantic スキーマ ──────────────────────────────────────────────────────────

class JobCreate(BaseModel):
    title: str
    company_name: str
    account_ids: List[str]
    is_partner_company: bool = False
    partner_company_id: Optional[str] = None
    postal_code: Optional[str] = None
    prefecture: str
    city: str
    address: Optional[str] = None
    is_remote: bool = False
    remote_type: str = "onsite"
    job_type: JobType
    salary_min: Optional[int] = None
    salary_max: Optional[int] = None
    salary_type: str = "monthly"
    salary_description: Optional[str] = None
    working_hours: Optional[str] = None
    holidays: Optional[str] = None
    benefits: Optional[str] = None
    requirements: Optional[str] = None
    description: str
    apply_url: Optional[str] = None
    category: Optional[str] = None
    keywords: Optional[List[str]] = None
    source_url: Optional[str] = None
    source_platform: Optional[str] = None
    is_republishable: bool = False
    republish_permission: Optional[str] = None
    has_probationary_period: ProbationaryPeriod = ProbationaryPeriod.UNKNOWN
    probationary_period_months: Optional[int] = None
    social_insurance_suids: Optional[List[str]] = None
    work_system_suids: Optional[List[str]] = None


class JobOut(BaseModel):
    id: str
    title: str
    company_name: str
    account_ids: List[str]
    prefecture: str
    city: str
    job_type: str
    status: str
    compliance_status: str
    expires_at: Optional[datetime]
    published_at: Optional[datetime]
    indeed_posting_ids: Optional[dict]

    class Config:
        from_attributes = True
