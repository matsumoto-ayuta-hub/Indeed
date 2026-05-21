"""
Zキャリア エクスポートExcel → Indeed 全自動インポートスクリプト。

使い方:
  # 本番実行（account_partner に同期）
  python scripts/import_zcareer.py --file path/to/export.xlsx

  # 複数アカウントへ同期
  python scripts/import_zcareer.py --file jobs.xlsx --accounts account_partner account_self

  # ドライラン（DBへの書き込みなし・内容確認のみ）
  python scripts/import_zcareer.py --file jobs.xlsx --dry-run

  # DBにだけ登録して Indeed 同期はスキップ（クレデンシャル未設定時）
  python scripts/import_zcareer.py --file jobs.xlsx --skip-indeed
"""
import sys
import os
import argparse
import time
import logging
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

logging.basicConfig(
    level=logging.WARNING,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)

from src.database import init_db, get_db
from src.config import ACCOUNT_IDS, ACCOUNT_CONFIG
from src.zcareer_importer import import_from_excel


def main():
    parser = argparse.ArgumentParser(
        description="Zキャリア エクスポートExcel → Indeed 全自動インポート"
    )
    parser.add_argument("--file", required=True, help="Zキャリアエクスポートファイル（.xlsx）")
    parser.add_argument(
        "--accounts",
        nargs="+",
        default=["account_partner"],
        choices=ACCOUNT_IDS,
        help="掲載先アカウントID（複数指定可、デフォルト: account_partner）",
    )
    parser.add_argument("--dry-run", action="store_true", help="DB・API への書き込みなし（検証のみ）")
    parser.add_argument("--skip-indeed", action="store_true", help="Indeed API 同期をスキップ")
    parser.add_argument("--batch-size", type=int, default=100, help="DBコミット単位（デフォルト: 100）")
    args = parser.parse_args()

    if not os.path.exists(args.file):
        print(f"エラー: ファイルが見つかりません: {args.file}")
        sys.exit(1)

    print("=" * 60)
    print("  Zキャリア → Indeed 全自動インポート")
    print("=" * 60)
    print(f"  ファイル  : {args.file}")
    print(f"  対象アカウント: {', '.join(args.accounts)}")
    print(f"  モード    : {'ドライラン（検証のみ）' if args.dry_run else '本番実行'}")
    print(f"  Indeed 同期: {'スキップ' if args.skip_indeed or args.dry_run else '有効'}")
    print()

    # アカウントのクレデンシャル確認
    sync = not args.skip_indeed and not args.dry_run
    if sync:
        for aid in args.accounts:
            cfg = ACCOUNT_CONFIG[aid]
            if not cfg.has_credentials:
                print(f"⚠️  [{aid}] OAuth クレデンシャルが未設定です。")
                print(f"   .env の ACCOUNT_{aid.upper().split('_')[1]}_CLIENT_ID/SECRET を設定してください。")
                print("   このアカウントへの Indeed 同期はスキップされます。")

    if not args.dry_run:
        init_db()

    start_time = time.time()

    with get_db() as db:
        result = import_from_excel(
            file_path=args.file,
            db=db,
            account_ids=args.accounts,
            sync_to_indeed=sync,
            batch_size=args.batch_size,
            dry_run=args.dry_run,
        )

    elapsed = time.time() - start_time

    print("\n")
    print("=" * 60)
    print("  インポート結果")
    print("=" * 60)
    print(f"  処理対象総数          : {result.total:,} 件")
    print(f"  新規登録              : {result.created:,} 件")
    print(f"  更新（既存求人）       : {result.updated:,} 件")
    print(f"  コンプライアンス失敗   : {result.compliance_failed:,} 件 ⚠️")
    if sync:
        print(f"  Indeed API 同期成功   : {result.indeed_synced:,} 件")
        print(f"  Indeed API 同期失敗   : {result.indeed_errors:,} 件")
    print(f"  処理時間              : {elapsed:.1f} 秒")
    print()

    if result.errors:
        print(f"  エラー詳細（先頭20件）:")
        for e in result.errors[:20]:
            print(f"    - {e}")
        if len(result.errors) > 20:
            print(f"    ... 他 {len(result.errors) - 20} 件")

    if args.dry_run:
        print()
        print("  ✅ ドライラン完了。実際のインポートは --dry-run なしで実行してください。")
    else:
        print("  ✅ インポート完了。")
        if sync:
            print()
            print("  次のコマンドで状態を確認できます:")
            print("    curl http://localhost:8000/api/admin/status")


if __name__ == "__main__":
    main()
