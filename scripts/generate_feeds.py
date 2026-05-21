"""全アカウントのフィードを手動で生成するスクリプト"""
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from src.database import init_db, get_db
from src.feed_generator import generate_all_feeds
from src.config import settings


def main():
    init_db()
    print("フィード生成開始...")
    with get_db() as db:
        results = generate_all_feeds(db)
    for account_id, path in results.items():
        print(f"  {account_id}: {path}")
        print(f"    → Indeed クロールURL: {settings.app_base_url}/feeds/{account_id}.xml")
    print("完了")


if __name__ == "__main__":
    main()
