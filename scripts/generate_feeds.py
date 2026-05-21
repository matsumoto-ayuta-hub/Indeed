"""
旧 XML フィード生成スクリプト（廃止）。
Indeed は 2026年3月31日に XML フィード（organic）を廃止しました。
Job Sync API（GraphQL）への同期は以下で実行してください:
  python scripts/setup_indeed.py        # 初期設定
  curl -X POST http://localhost:8000/api/admin/sync   # 手動同期
"""
print("⚠️  XML フィードは Indeed により 2026年3月31日に廃止されました。")
print("   Job Sync API を使った同期は以下で実行してください:")
print("   python scripts/setup_indeed.py")
print("   curl -X POST http://localhost:8000/api/admin/sync")
