"""
APScheduler による定期実行タスク。
- フィード生成（6時間ごと）
- 有効期限チェック（毎日）
- 自動更新（毎日）
"""
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.interval import IntervalTrigger
from apscheduler.triggers.cron import CronTrigger
import logging

from .config import settings
from .database import SessionLocal
from .job_manager import JobManager
from .feed_generator import generate_all_feeds

logger = logging.getLogger(__name__)


def task_generate_feeds():
    logger.info("フィード生成タスク開始")
    db = SessionLocal()
    try:
        results = generate_all_feeds(db)
        for account_id, path in results.items():
            logger.info(f"  {account_id}: {path}")
    except Exception as e:
        logger.error(f"フィード生成エラー: {e}")
    finally:
        db.close()


def task_expire_jobs():
    logger.info("有効期限チェックタスク開始")
    db = SessionLocal()
    try:
        mgr = JobManager(db)
        count = mgr.expire_old_jobs()
        logger.info(f"  {count}件の求人を期限切れに更新")
    except Exception as e:
        logger.error(f"有効期限チェックエラー: {e}")
    finally:
        db.close()


def task_auto_renew():
    logger.info("自動更新タスク開始")
    db = SessionLocal()
    try:
        mgr = JobManager(db)
        renewed = mgr.auto_renew_expiring()
        logger.info(f"  {len(renewed)}件の求人を自動更新: {renewed}")
        # 更新後にフィードを再生成
        generate_all_feeds(db)
    except Exception as e:
        logger.error(f"自動更新エラー: {e}")
    finally:
        db.close()


def create_scheduler() -> BackgroundScheduler:
    scheduler = BackgroundScheduler(timezone="Asia/Tokyo")

    # フィード生成: N時間ごと
    scheduler.add_job(
        task_generate_feeds,
        trigger=IntervalTrigger(hours=settings.feed_refresh_interval_hours),
        id="generate_feeds",
        replace_existing=True,
    )

    # 有効期限チェック: 毎日 0:00
    scheduler.add_job(
        task_expire_jobs,
        trigger=CronTrigger(hour=0, minute=0),
        id="expire_jobs",
        replace_existing=True,
    )

    # 自動更新: 毎日 1:00
    scheduler.add_job(
        task_auto_renew,
        trigger=CronTrigger(hour=1, minute=0),
        id="auto_renew",
        replace_existing=True,
    )

    return scheduler
