"""
FastAPI アプリケーション。
- /api/jobs         → 求人 CRUD
- /api/accounts     → アカウント情報・同期ステータス
- /api/admin/*      → 管理操作（強制同期・期限チェック等）
"""
import os
from contextlib import asynccontextmanager
from datetime import datetime
from typing import Optional

from fastapi import FastAPI, Depends, HTTPException, Query, UploadFile, File, BackgroundTasks
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session

from .config import settings, ACCOUNT_CONFIG, ACCOUNT_IDS
from .database import init_db, get_db_dep, SessionLocal
from .models import Job, JobCreate, JobStatus, ComplianceStatus, SyncLog
from .job_manager import JobManager
from .scheduler import create_scheduler
from .zcareer_importer import import_from_excel

scheduler = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    global scheduler
    init_db()
    os.makedirs("data", exist_ok=True)
    scheduler = create_scheduler()
    scheduler.start()
    yield
    if scheduler:
        scheduler.shutdown()


app = FastAPI(
    title="Indeed Job Sync System",
    description="Indeed Japan 求人自動管理システム（有料職業紹介事業者向け / Job Sync API 対応）",
    version="2.0.0",
    lifespan=lifespan,
)


# ── アカウント情報 ────────────────────────────────────────────────────────────

@app.get("/api/accounts", tags=["Accounts"])
async def list_accounts(db: Session = Depends(get_db_dep)):
    result = []
    for aid, cfg in ACCOUNT_CONFIG.items():
        active_jobs = db.query(Job).filter(
            Job.status == JobStatus.ACTIVE
        ).all()
        active_in_account = sum(1 for j in active_jobs if aid in (j.account_ids or []))
        result.append({
            "id": aid,
            "publisher_name": cfg.publisher_name,
            "description": cfg.description,
            "has_credentials": cfg.has_credentials,
            "allow_partner_jobs": cfg.allow_partner_jobs,
            "allow_own_jobs": cfg.allow_own_jobs,
            "max_jobs": cfg.max_jobs,
            "active_job_count": active_in_account,
        })
    return result


# ── 求人 CRUD ─────────────────────────────────────────────────────────────────

@app.post("/api/jobs", tags=["Jobs"], status_code=201)
async def create_job(data: JobCreate, db: Session = Depends(get_db_dep)):
    mgr = JobManager(db)
    job = mgr.create_job(data, auto_check=True)
    return {
        "id": job.id,
        "job_reference_number": job.job_reference_number,
        "status": job.status.value,
        "compliance_status": job.compliance_status.value,
        "compliance_notes": job.compliance_notes,
        "description_modified": job.description_modified,
    }


@app.get("/api/jobs", tags=["Jobs"])
async def list_jobs(
    account_id: Optional[str] = Query(None),
    status: Optional[str] = Query(None),
    limit: int = Query(100, le=1000),
    db: Session = Depends(get_db_dep),
):
    mgr = JobManager(db)
    st = JobStatus(status) if status else None
    jobs = mgr.get_jobs(account_id=account_id, status=st, limit=limit)
    return [
        {
            "id": j.id,
            "title": j.title,
            "company_name": j.company_name,
            "account_ids": j.account_ids,
            "job_type": j.job_type.value if hasattr(j.job_type, "value") else j.job_type,
            "status": j.status.value if hasattr(j.status, "value") else j.status,
            "compliance_status": j.compliance_status.value if hasattr(j.compliance_status, "value") else j.compliance_status,
            "indeed_posting_ids": j.indeed_posting_ids,
            "last_sync_at": j.last_sync_at,
            "sync_errors": j.sync_errors,
            "expires_at": j.expires_at.isoformat() if j.expires_at else None,
        }
        for j in jobs
    ]


@app.get("/api/jobs/{job_id}", tags=["Jobs"])
async def get_job(job_id: str, db: Session = Depends(get_db_dep)):
    job = db.query(Job).filter_by(id=job_id).first()
    if not job:
        raise HTTPException(404, "求人が見つかりません")
    return {
        "id": job.id,
        "title": job.title,
        "company_name": job.company_name,
        "description": job.description,
        "description_modified": job.description_modified,
        "compliance_notes": job.compliance_notes,
        "status": job.status.value if hasattr(job.status, "value") else job.status,
        "compliance_status": job.compliance_status.value if hasattr(job.compliance_status, "value") else job.compliance_status,
        "indeed_posting_ids": job.indeed_posting_ids,
        "last_sync_at": job.last_sync_at,
        "sync_errors": job.sync_errors,
        "expires_at": job.expires_at.isoformat() if job.expires_at else None,
        "has_probationary_period": job.has_probationary_period.value if job.has_probationary_period else None,
        "social_insurance_suids": job.social_insurance_suids,
        "work_system_suids": job.work_system_suids,
    }


@app.post("/api/jobs/{job_id}/publish", tags=["Jobs"])
async def publish_job(job_id: str, db: Session = Depends(get_db_dep)):
    mgr = JobManager(db)
    try:
        job = mgr.publish(job_id)
    except ValueError as e:
        raise HTTPException(400, str(e))
    if not job:
        raise HTTPException(404, "求人が見つかりません")
    return {
        "id": job.id,
        "status": job.status.value,
        "indeed_posting_ids": job.indeed_posting_ids,
        "sync_errors": job.sync_errors,
        "expires_at": job.expires_at.isoformat() if job.expires_at else None,
    }


@app.post("/api/jobs/{job_id}/renew", tags=["Jobs"])
async def renew_job(job_id: str, db: Session = Depends(get_db_dep)):
    mgr = JobManager(db)
    job = mgr.renew(job_id)
    if not job:
        raise HTTPException(404, "求人が見つかりません")
    return {
        "id": job.id,
        "status": job.status.value,
        "expires_at": job.expires_at.isoformat() if job.expires_at else None,
    }


@app.post("/api/jobs/{job_id}/expire", tags=["Jobs"])
async def expire_job(job_id: str, db: Session = Depends(get_db_dep)):
    mgr = JobManager(db)
    job = mgr.expire_job(job_id)
    if not job:
        raise HTTPException(404, "求人が見つかりません")
    return {"id": job.id, "status": job.status.value}


@app.post("/api/jobs/{job_id}/check", tags=["Jobs"])
async def recheck_compliance(job_id: str, db: Session = Depends(get_db_dep)):
    job = db.query(Job).filter_by(id=job_id).first()
    if not job:
        raise HTTPException(404, "求人が見つかりません")
    mgr = JobManager(db)
    mgr._run_compliance(job)
    db.commit()
    return {
        "compliance_status": job.compliance_status.value if hasattr(job.compliance_status, "value") else job.compliance_status,
        "compliance_notes": job.compliance_notes,
        "description_modified": job.description_modified,
    }


# ── 管理操作 ──────────────────────────────────────────────────────────────────

@app.post("/api/admin/sync", tags=["Admin"])
async def trigger_sync(
    account_id: Optional[str] = Query(None),
    db: Session = Depends(get_db_dep),
):
    if account_id and account_id not in ACCOUNT_IDS:
        raise HTTPException(404, "アカウントが見つかりません")
    mgr = JobManager(db)
    result = mgr.sync_all_active(account_id=account_id)
    return result


@app.post("/api/admin/expire-check", tags=["Admin"])
async def trigger_expire_check(db: Session = Depends(get_db_dep)):
    mgr = JobManager(db)
    count = mgr.expire_old_jobs()
    return {"expired_count": count}


@app.post("/api/admin/auto-renew", tags=["Admin"])
async def trigger_auto_renew(db: Session = Depends(get_db_dep)):
    mgr = JobManager(db)
    renewed = mgr.auto_renew_expiring()
    return {"renewed_job_ids": renewed, "count": len(renewed)}


@app.post("/api/admin/import/zcareer", tags=["Admin"])
async def import_zcareer(
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...),
    accounts: str = Query("account_partner", description="カンマ区切りのアカウントID"),
    skip_indeed: bool = Query(False),
):
    """Zキャリア エクスポートExcel をアップロードして全自動インポート（バックグラウンド実行）"""
    import tempfile, shutil
    account_ids = [a.strip() for a in accounts.split(",") if a.strip() in ACCOUNT_IDS]
    if not account_ids:
        raise HTTPException(400, "有効なアカウントIDが指定されていません")

    # 一時ファイルに保存
    suffix = os.path.splitext(file.filename or "upload")[1] or ".xlsx"
    tmp = tempfile.NamedTemporaryFile(delete=False, suffix=suffix)
    shutil.copyfileobj(file.file, tmp)
    tmp.close()

    def run_import(path: str, accs: list, sync: bool):
        db = SessionLocal()
        try:
            result = import_from_excel(path, db, account_ids=accs, sync_to_indeed=sync)
            print(
                f"[zcareer import] 完了: 新規={result.created} 更新={result.updated} "
                f"失敗={result.compliance_failed} Indeed同期={result.indeed_synced}"
            )
        finally:
            db.close()
            os.unlink(path)

    background_tasks.add_task(run_import, tmp.name, account_ids, not skip_indeed)
    return {
        "message": "インポートをバックグラウンドで開始しました",
        "accounts": account_ids,
        "file": file.filename,
    }


@app.get("/api/admin/status", tags=["Admin"])
async def system_status(db: Session = Depends(get_db_dep)):
    total = db.query(Job).count()
    active = db.query(Job).filter(Job.status == JobStatus.ACTIVE).count()
    pending = db.query(Job).filter(Job.status == JobStatus.PENDING_REVIEW).count()
    rejected = db.query(Job).filter(Job.status == JobStatus.REJECTED).count()

    last_sync = db.query(SyncLog).order_by(SyncLog.synced_at.desc()).first()
    accounts = []
    for aid, cfg in ACCOUNT_CONFIG.items():
        accounts.append({
            "id": aid,
            "has_credentials": cfg.has_credentials,
            "publisher_name": cfg.publisher_name,
        })

    return {
        "jobs": {
            "total": total,
            "active": active,
            "pending": pending,
            "rejected": rejected,
        },
        "accounts": accounts,
        "last_sync": {
            "synced_at": last_sync.synced_at.isoformat() if last_sync else None,
            "created": last_sync.created_count if last_sync else 0,
            "updated": last_sync.updated_count if last_sync else 0,
            "errors": last_sync.error_count if last_sync else 0,
        },
        "scheduler_running": scheduler is not None and scheduler.running,
        "agency_license_number": settings.agency_license_number,
        "agency_name": settings.agency_name,
    }
