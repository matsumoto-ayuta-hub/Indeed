"""
Excel/CSV から求人を一括インポートするスクリプト。

使い方:
  python scripts/import_jobs.py --file jobs.xlsx --account account_partner
  python scripts/import_jobs.py --file jobs.csv --account account_self --dry-run

Excel の列名（ヘッダー行が必要）:
  title, company_name, prefecture, city, address, postal_code,
  job_type, salary_min, salary_max, salary_type, salary_description,
  working_hours, holidays, benefits, requirements, description,
  apply_url, category, is_remote, remote_type,
  is_partner_company, source_url, is_republishable
"""
import sys
import os
import argparse
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from src.database import init_db, get_db
from src.models import JobCreate, JobType
from src.job_manager import JobManager
from src.config import ACCOUNT_IDS


REQUIRED_COLUMNS = ["title", "company_name", "prefecture", "city", "job_type", "description"]

JOB_TYPE_MAP = {
    "正社員": "fulltime",
    "パート": "parttime",
    "アルバイト": "parttime",
    "パート・アルバイト": "parttime",
    "契約社員": "contract",
    "派遣社員": "temporary",
    "派遣": "temporary",
    "インターン": "internship",
    "インターンシップ": "internship",
    "業務委託": "freelance",
    "フリーランス": "freelance",
    "fulltime": "fulltime",
    "parttime": "parttime",
    "contract": "contract",
    "temporary": "temporary",
    "internship": "internship",
    "freelance": "freelance",
}


def parse_row(row: dict, account_id: str) -> JobCreate:
    job_type_raw = str(row.get("job_type", "fulltime")).strip()
    job_type = JOB_TYPE_MAP.get(job_type_raw, "fulltime")

    def safe_int(val):
        try:
            return int(float(val)) if pd.notna(val) and val != "" else None
        except (ValueError, TypeError):
            return None

    def safe_str(val):
        return str(val).strip() if pd.notna(val) and val != "" else None

    def safe_bool(val):
        if pd.isna(val) or val == "":
            return False
        return str(val).lower() in ("true", "1", "yes", "はい", "TRUE")

    return JobCreate(
        title=str(row["title"]).strip(),
        company_name=str(row["company_name"]).strip(),
        account_ids=[account_id],
        is_partner_company=safe_bool(row.get("is_partner_company", False)),
        postal_code=safe_str(row.get("postal_code")),
        prefecture=str(row["prefecture"]).strip(),
        city=str(row["city"]).strip(),
        address=safe_str(row.get("address")),
        is_remote=safe_bool(row.get("is_remote", False)),
        remote_type=safe_str(row.get("remote_type")) or "onsite",
        job_type=JobType(job_type),
        salary_min=safe_int(row.get("salary_min")),
        salary_max=safe_int(row.get("salary_max")),
        salary_type=safe_str(row.get("salary_type")) or "monthly",
        salary_description=safe_str(row.get("salary_description")),
        working_hours=safe_str(row.get("working_hours")),
        holidays=safe_str(row.get("holidays")),
        benefits=safe_str(row.get("benefits")),
        requirements=safe_str(row.get("requirements")),
        description=str(row["description"]).strip(),
        apply_url=safe_str(row.get("apply_url")),
        category=safe_str(row.get("category")),
        source_url=safe_str(row.get("source_url")),
        is_republishable=safe_bool(row.get("is_republishable", False)),
    )


def main():
    parser = argparse.ArgumentParser(description="Indeed求人一括インポート")
    parser.add_argument("--file", required=True, help="インポートするExcel/CSVファイルパス")
    parser.add_argument("--account", required=True, choices=ACCOUNT_IDS, help="掲載先アカウントID")
    parser.add_argument("--dry-run", action="store_true", help="実際にはインポートしない（検証のみ）")
    parser.add_argument("--no-check", action="store_true", help="コンプライアンスチェックをスキップ")
    args = parser.parse_args()

    if not os.path.exists(args.file):
        print(f"エラー: ファイルが見つかりません: {args.file}")
        sys.exit(1)

    if args.file.endswith(".xlsx") or args.file.endswith(".xls"):
        df = pd.read_excel(args.file, dtype=str)
    else:
        df = pd.read_csv(args.file, dtype=str)

    # 必須列チェック
    missing = [c for c in REQUIRED_COLUMNS if c not in df.columns]
    if missing:
        print(f"エラー: 必須列が不足しています: {missing}")
        print(f"現在の列: {list(df.columns)}")
        sys.exit(1)

    print(f"対象ファイル: {args.file}")
    print(f"掲載アカウント: {args.account}")
    print(f"求人数: {len(df)}件")
    print(f"モード: {'ドライラン（検証のみ）' if args.dry_run else '本番インポート'}")
    print("-" * 50)

    if args.dry_run:
        errors = []
        for i, row in df.iterrows():
            try:
                parse_row(row.to_dict(), args.account)
                print(f"  [{i+1}] OK: {row.get('title', '不明')} / {row.get('company_name', '不明')}")
            except Exception as e:
                errors.append((i+1, str(e)))
                print(f"  [{i+1}] ERROR: {e}")
        print(f"\nドライラン完了: {len(df) - len(errors)}件OK / {len(errors)}件エラー")
        return

    init_db()
    success = 0
    errors = []

    with get_db() as db:
        mgr = JobManager(db)
        for i, row in df.iterrows():
            try:
                data = parse_row(row.to_dict(), args.account)
                job = mgr.create_job(data, auto_check=not args.no_check)
                status = job.compliance_status.value if hasattr(job.compliance_status, "value") else str(job.compliance_status)
                print(f"  [{i+1}] インポート完了: {data.title} / {data.company_name} → {status}")
                success += 1
            except Exception as e:
                errors.append((i+1, str(e)))
                print(f"  [{i+1}] ERROR: {e}")

    print(f"\nインポート完了: {success}/{len(df)}件成功 / {len(errors)}件エラー")
    if errors:
        print("エラー詳細:")
        for row_num, msg in errors:
            print(f"  行{row_num}: {msg}")


if __name__ == "__main__":
    main()
