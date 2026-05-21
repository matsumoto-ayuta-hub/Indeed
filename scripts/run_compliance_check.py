"""
指定アカウントの未チェック求人に対してコンプライアンスチェックを一括実行するスクリプト。

使い方:
  python scripts/run_compliance_check.py
  python scripts/run_compliance_check.py --account account_partner
  python scripts/run_compliance_check.py --status pending_review
"""
import sys
import os
import argparse

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from src.database import init_db, get_db
from src.models import Job, JobStatus, ComplianceStatus
from src.job_manager import JobManager
from src.config import ACCOUNT_IDS


def main():
    parser = argparse.ArgumentParser(description="コンプライアンス一括チェック")
    parser.add_argument("--account", choices=ACCOUNT_IDS, help="対象アカウントID（省略時は全アカウント）")
    parser.add_argument("--status", default="pending_review", help="対象ステータス（デフォルト: pending_review）")
    parser.add_argument("--all", action="store_true", help="全求人を再チェック（ステータス無関係）")
    args = parser.parse_args()

    init_db()

    with get_db() as db:
        q = db.query(Job)
        if not args.all:
            q = q.filter(Job.compliance_status == ComplianceStatus.UNCHECKED)
        jobs = q.all()

        if args.account:
            jobs = [j for j in jobs if args.account in (j.account_ids or [])]

        print(f"チェック対象: {len(jobs)}件")
        mgr = JobManager(db)

        for i, job in enumerate(jobs, 1):
            print(f"[{i}/{len(jobs)}] {job.title} / {job.company_name}", end=" ... ")
            try:
                mgr._run_compliance(job)
                db.flush()
                status = job.compliance_status.value if hasattr(job.compliance_status, "value") else str(job.compliance_status)
                print(status)
                if job.compliance_notes:
                    issues = [iss for iss in job.compliance_notes if iss.get("severity") == "critical"]
                    if issues:
                        for iss in issues:
                            print(f"    [CRITICAL] {iss.get('issue', '')}")
            except Exception as e:
                print(f"ERROR: {e}")

        db.commit()
    print("コンプライアンスチェック完了")


if __name__ == "__main__":
    main()
