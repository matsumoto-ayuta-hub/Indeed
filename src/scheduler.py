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


def task_import_zcareer_if_new():
    """設定されたフォルダに新しい Zキャリアファイルがあれば自動インポートする"""
    import glob, os
    watch_dir = os.environ.get("ZCAREER_WATCH_DIR", "")
    if not watch_dir or not os.path.isdir(watch_dir):
        return

    pattern = os.path.join(watch_dir, "*.xlsx")
    files = sorted(glob.glob(pattern), key=os.path.getmtime, reverse=True)
    if not files:
        return

    latest = files[0]
    processed_marker = latest + ".imported"
    if os.path.exists(processed_marker):
        return

    logger.info(f"Zキャリア新規ファイルを検出: {latest}")
    from .zcareer_importer import import_from_excel
    db = SessionLocal()
    try:
        result = import_from_excel(latest, db, account_ids=["account_partner"])
        logger.info(
            f"自動インポート完了: 新規={result.created} 更新={result.updated} "
            f"失敗={result.compliance_failed}"
        )
        open(processed_marker, "w").close()
    except Exception as e:
        logger.error(f"自動インポートエラー: {e}")
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

    # Zキャリア自動インポート: 毎日 2:00（ZCAREER_WATCH_DIR 設定時のみ有効）
    scheduler.add_job(
        task_import_zcareer_if_new,
        trigger=CronTrigger(hour=2, minute=0),
        id="zcareer_auto_import",
        replace_existing=True,
    )

    return scheduler
