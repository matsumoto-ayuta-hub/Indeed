"""
FastAPI アプリケーション。
- /feeds/{account_id}.xml  → Indeed がクロールするXMLフィードを配信
- /api/jobs                → 求人CRUD API
- /api/accounts            → アカウント情報
- /api/admin/*             → 管理操作
"""
import os
from contextlib import asynccontextmanager
from datetime import datetime
from typing import Optional
from fastapi import FastAPI, Depends, HTTPException, BackgroundTasks, Query
from fastapi.responses import FileResponse, JSONResponse
from sqlalchemy.orm import Session

from .config import settings, ACCOUNT_CONFIG, ACCOUNT_IDS
from .database import init_db, get_db_dep
from .models import JobCreate, JobStatus, ComplianceStatus
from .job_manager import JobManager
from .feed_generator import generate_all_feeds, generate_feed_for_account
from .scheduler import create_scheduler

scheduler = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    global scheduler
    init_db()
    os.makedirs("feeds", exist_ok=True)
    os.makedirs("data", exist_ok=True)
    scheduler = create_scheduler()
    scheduler.start()
    yield
    if scheduler:
        scheduler.shutdown()


app = FastAPI(
    title="Indeed Job Sync System",
    description="Indeed Japan 求人自動管理・転載システム（有料職業紹介事業者向け）",
    version="1.0.0",
    lifespan=lifespan,
)


# ── フィード配信 ──────────────────────────────────────────────────────────────

@app.get(
    "/feeds/{account_id}.xml",
    response_class=FileResponse,
    tags=["Feeds"],
    summary="Indeed XML Job Feed",
)
async def get_feed(account_id: str):
    if account_id not in ACCOUNT_IDS:
        raise HTTPException(404, "アカウントが見つかりません")
    path = f"feeds/{account_id}.xml"
    if not os.path.exists(path):
        raise HTTPException(503, "フィードがまだ生成されていません。/api/admin/feeds/generate を実行してください。")
    return FileResponse(path, media_type="application/xml; charset=utf-8")


# ── アカウント情報 ────────────────────────────────────────────────────────────

@app.get("/api/accounts", tags=["Accounts"])
async def list_accounts():
    return [
        {
            "id": aid,
            "feed_url": f"{settings.app_base_url}/feeds/{aid}.xml",
            **ACCOUNT_CONFIG[aid],
        }
        for aid in ACCOUNT_IDS
    ]


# ── 求人 CRUD ─────────────────────────────────────────────────────────────────

@app.post("/api/jobs", tags=["Jobs"], status_code=201)
async def create_job(
    data: JobCreate,
    db: Session = Depends(get_db_dep),
):
    mgr = JobManager(db)
    job = mgr.create_job(data, auto_check=True)
    return {
        "id": job.id,
        "job_reference_number": job.job_reference_number,
        "status": job.status.value,
        "compliance_status": job.compliance_status.value,
        "compliance_notes": job.compliance_notes,
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
            "expires_at": j.expires_at.isoformat() if j.expires_at else None,
            "prefecture": j.prefecture,
            "city": j.city,
        }
        for j in jobs
    ]


@app.get("/api/jobs/{job_id}", tags=["Jobs"])
async def get_job(job_id: str, db: Session = Depends(get_db_dep)):
    job = db.query(__import__("src.models", fromlist=["Job"]).Job).filter_by(id=job_id).first()
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
        "expires_at": job.expires_at.isoformat() if job.expires_at else None,
        "apply_url": job.apply_url,
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
    return {"id": job.id, "status": job.status.value, "expires_at": job.expires_at.isoformat()}


@app.post("/api/jobs/{job_id}/renew", tags=["Jobs"])
async def renew_job(job_id: str, db: Session = Depends(get_db_dep)):
    mgr = JobManager(db)
    job = mgr.renew(job_id)
    if not job:
        raise HTTPException(404, "求人が見つかりません")
    return {"id": job.id, "status": job.status.value, "expires_at": job.expires_at.isoformat()}


@app.post("/api/jobs/{job_id}/check", tags=["Jobs"])
async def recheck_compliance(job_id: str, db: Session = Depends(get_db_dep)):
    from .models import Job
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

@app.post("/api/admin/feeds/generate", tags=["Admin"])
async def trigger_feed_generation(
    background_tasks: BackgroundTasks,
    account_id: Optional[str] = Query(None),
    db: Session = Depends(get_db_dep),
):
    if account_id:
        if account_id not in ACCOUNT_IDS:
            raise HTTPException(404, "アカウントが見つかりません")
        path = generate_feed_for_account(account_id, db)
        return {"account_id": account_id, "path": path}
    results = generate_all_feeds(db)
    return results


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


@app.get("/api/admin/status", tags=["Admin"])
async def system_status(db: Session = Depends(get_db_dep)):
    from .models import Job
    total = db.query(Job).count()
    active = db.query(Job).filter(Job.status == JobStatus.ACTIVE).count()
    pending = db.query(Job).filter(Job.status == JobStatus.PENDING_REVIEW).count()
    rejected = db.query(Job).filter(Job.status == JobStatus.REJECTED).count()

    feeds = {}
    for aid in ACCOUNT_IDS:
        path = f"feeds/{aid}.xml"
        feeds[aid] = {
            "exists": os.path.exists(path),
            "url": f"{settings.app_base_url}/feeds/{aid}.xml",
            "updated_at": (
                datetime.utcfromtimestamp(os.path.getmtime(path)).isoformat()
                if os.path.exists(path) else None
            ),
        }

    return {
        "jobs": {"total": total, "active": active, "pending": pending, "rejected": rejected},
        "feeds": feeds,
        "scheduler_running": scheduler is not None and scheduler.running,
    }
