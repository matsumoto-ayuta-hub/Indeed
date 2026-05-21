from datetime import datetime, date
from enum import Enum
from typing import Optional, List
from sqlalchemy import (
    Column, String, Text, DateTime, Date, Boolean, Integer,
    Float, ForeignKey, JSON, Enum as SAEnum, UniqueConstraint, Index
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


class Job(Base):
    __tablename__ = "jobs"

    id = Column(String(36), primary_key=True)
    # どのIndeedアカウントに掲載するか（複数可）
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
    remote_type = Column(String(20))  # "onsite", "remote", "hybrid"

    # 雇用条件
    job_type = Column(SAEnum(JobType), nullable=False)
    salary_min = Column(Integer)
    salary_max = Column(Integer)
    salary_type = Column(String(20))  # "monthly", "hourly", "annual"
    salary_description = Column(String(500))
    working_hours = Column(String(500))
    holidays = Column(String(500))
    benefits = Column(Text)
    requirements = Column(Text)

    # 求人内容
    description = Column(Text, nullable=False)
    description_modified = Column(Text)  # コンプライアンス修正後

    # Indeed用URL（応募リンク）
    apply_url = Column(String(500))
    job_reference_number = Column(String(100), unique=True)

    # カテゴリ
    category = Column(String(100))
    subcategory = Column(String(100))
    keywords = Column(JSON)

    # ステータス管理
    status = Column(SAEnum(JobStatus), default=JobStatus.DRAFT)
    compliance_status = Column(SAEnum(ComplianceStatus), default=ComplianceStatus.UNCHECKED)
    compliance_notes = Column(JSON)

    # 日付管理
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    published_at = Column(DateTime)
    expires_at = Column(DateTime)
    last_renewed_at = Column(DateTime)
    source_updated_at = Column(DateTime)  # 元求人の更新日時

    # 転載情報
    source_url = Column(String(500))
    source_platform = Column(String(100))
    is_republishable = Column(Boolean, default=False)
    republish_permission = Column(String(100))

    partner_company = relationship("PartnerCompany", back_populates="jobs")
    compliance_logs = relationship("ComplianceLog", back_populates="job", order_by="ComplianceLog.checked_at.desc()")

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
    contract_type = Column(String(50))  # "full_partner", "referral", "listing_only"
    allowed_accounts = Column(JSON)  # どのアカウントへの掲載が許可されているか
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


class FeedLog(Base):
    __tablename__ = "feed_logs"

    id = Column(Integer, primary_key=True, autoincrement=True)
    account_id = Column(String(100), nullable=False)
    generated_at = Column(DateTime, default=datetime.utcnow)
    job_count = Column(Integer, default=0)
    file_path = Column(String(500))
    success = Column(Boolean, default=True)
    error_message = Column(Text)


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

    class Config:
        from_attributes = True
