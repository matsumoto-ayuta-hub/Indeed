"""
APScheduler による定期実行タスク。
- Indeed API への全求人同期（N時間ごと）
- 有効期限チェック（毎日 0:00）
- 自動リニュー（毎日 1:00）
"""
import logging
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.interval import IntervalTrigger
from apscheduler.triggers.cron import CronTrigger

from .config import settings
from .database import SessionLocal
from .job_manager import JobManager

logger = logging.getLogger(__name__)


def task_sync_to_indeed():
    logger.info("Indeed API 同期タスク開始")
    db = SessionLocal()
    try:
        mgr = JobManager(db)
        result = mgr.sync_all_active()
        logger.info(
            f"  同期完了: 新規={result['created']} 更新={result['updated']} "
            f"エラー={result['errors']}"
        )
    except Exception as e:
        logger.error(f"Indeed 同期エラー: {e}")
    finally:
        db.close()


def task_expire_jobs():
    logger.info("有効期限チェックタスク開始")
    db = SessionLocal()
    try:
        mgr = JobManager(db)
        count = mgr.expire_old_jobs()
        logger.info(f"  {count}件の求人を期限切れに更新（Indeed 側も取り下げ済み）")
    except Exception as e:
        logger.error(f"有効期限チェックエラー: {e}")
    finally:
        db.close()


def task_auto_renew():
    logger.info("自動リニュータスク開始")
    db = SessionLocal()
    try:
        mgr = JobManager(db)
        renewed = mgr.auto_renew_expiring()
        logger.info(f"  {len(renewed)}件の求人を自動リニュー: {renewed}")
    except Exception as e:
        logger.error(f"自動リニューエラー: {e}")
    finally:
        db.close()


def create_scheduler() -> BackgroundScheduler:
    scheduler = BackgroundScheduler(timezone="Asia/Tokyo")

    # Indeed API 同期: N時間ごと
    scheduler.add_job(
        task_sync_to_indeed,
        trigger=IntervalTrigger(hours=settings.sync_interval_hours),
        id="sync_to_indeed",
        replace_existing=True,
    )
    # 有効期限チェック: 毎日 0:00
    scheduler.add_job(
        task_expire_jobs,
        trigger=CronTrigger(hour=0, minute=0),
        id="expire_jobs",
        replace_existing=True,
    )
    # 自動リニュー: 毎日 1:00
    scheduler.add_job(
        task_auto_renew,
        trigger=CronTrigger(hour=1, minute=0),
        id="auto_renew",
        replace_existing=True,
    )

    return scheduler
