# Indeed Job Sync System

有料職業紹介事業者向けの Indeed Japan 求人自動管理・転載システム。

## セットアップ

```bash
pip install -r requirements.txt
cp .env.example .env
# .env を編集して各種APIキー・設定を記入
```

## 起動

```bash
uvicorn src.api:app --reload --port 8000
```

## 主要コマンド

```bash
# サンプルデータ登録
python scripts/sample_data.py

# Excel/CSV から求人インポート
python scripts/import_jobs.py --file jobs.xlsx --account account_partner

# XMLフィード手動生成
python scripts/generate_feeds.py

# コンプライアンス一括チェック
python scripts/run_compliance_check.py
```

## アーキテクチャ

- `src/config.py` — 設定・アカウント定義
- `src/models.py` — SQLAlchemy モデル + Pydantic スキーマ
- `src/compliance.py` — Claude API によるコンプライアンスチェック
- `src/feed_generator.py` — Indeed XML Job Feed 生成
- `src/job_manager.py` — 求人CRUD・自動更新ロジック
- `src/scheduler.py` — APScheduler 定期タスク
- `src/api.py` — FastAPI エンドポイント

## フィードURL（Indeed に登録するURL）

- アカウント1（自社採用）: `https://your-domain.com/feeds/account_self.xml`
- アカウント2（インターン）: `https://your-domain.com/feeds/account_intern.xml`
- アカウント3（提携先）: `https://your-domain.com/feeds/account_partner.xml`
