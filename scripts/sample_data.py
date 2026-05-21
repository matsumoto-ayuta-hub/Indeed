"""
動作確認用サンプル求人データを登録するスクリプト。
実際の運用では import_jobs.py を使ってExcel/CSVからインポートする。
"""
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from src.database import init_db, get_db
from src.models import JobCreate, JobType
from src.job_manager import JobManager


SAMPLE_JOBS = [
    # 自社採用 - 正社員
    JobCreate(
        title="Webエンジニア（バックエンド）",
        company_name="株式会社キャリアジャパン",
        account_ids=["account_self"],
        is_partner_company=False,
        prefecture="東京都",
        city="渋谷区",
        address="渋谷1-1-1",
        postal_code="150-0001",
        job_type=JobType.FULLTIME,
        salary_min=4000000,
        salary_max=7000000,
        salary_type="annual",
        working_hours="09:00〜18:00（休憩1時間）フレックスタイム制",
        holidays="完全週休2日制（土日）、祝日、年末年始、有給休暇",
        benefits="交通費全額支給、社会保険完備、リモートワーク可、研修制度あり",
        requirements="Python/Java/GoいずれかのWebバックエンド開発経験3年以上",
        description="""Webアプリケーションのバックエンド開発を担当していただきます。
マイクロサービスアーキテクチャでの開発経験者を歓迎します。
チームは10名構成で、アジャイル開発を採用しています。
新技術の導入にも積極的で、個人の成長を会社全体でサポートする環境です。""",
        category="IT・エンジニア",
        is_republishable=False,
    ),
    # インターン
    JobCreate(
        title="Webマーケティングインターン",
        company_name="株式会社キャリアジャパン",
        account_ids=["account_intern"],
        is_partner_company=False,
        prefecture="東京都",
        city="渋谷区",
        postal_code="150-0001",
        job_type=JobType.INTERNSHIP,
        salary_min=1200,
        salary_max=1500,
        salary_type="hourly",
        working_hours="週2〜3日、1日3〜8時間（授業優先でOK）",
        holidays="シフト制",
        benefits="交通費全額支給、インターン修了証発行",
        requirements="大学生・大学院生（学年不問）、マーケティングへの関心があること",
        description="""SNSマーケティングやコンテンツ制作を通じて実践的なスキルを習得できます。
業務内容：SNS運用補助、記事作成、データ分析レポート作成
実際のビジネス現場で即戦力として活躍していただける環境です。
就活サポートあり・正社員登用実績あり。""",
        category="マーケティング",
        is_republishable=False,
    ),
    # 提携先企業求人（転載）
    JobCreate(
        title="営業職（法人向けSaaS）",
        company_name="株式会社テクノソリューション",
        account_ids=["account_partner", "account_self"],
        is_partner_company=True,
        prefecture="大阪府",
        city="大阪市北区",
        postal_code="530-0001",
        job_type=JobType.FULLTIME,
        salary_min=3500000,
        salary_max=6000000,
        salary_type="annual",
        working_hours="09:00〜18:00（フレックス制、コアタイム10:00〜15:00）",
        holidays="完全週休2日制（土日祝）、有給休暇20日",
        benefits="インセンティブあり、各種社会保険、資格取得支援",
        requirements="法人営業経験1年以上。SaaS製品の営業経験者優遇",
        description="""中小〜中堅企業向けの業務効率化SaaSソリューションの提案営業をお任せします。
既存顧客への深耕営業と新規開拓を組み合わせた業務内容です。
1人あたりの担当社数は30〜50社程度で、週1〜2回の訪問営業が中心となります。""",
        category="営業",
        source_url="https://example-partner.com/jobs/001",
        is_republishable=True,
        republish_permission="書面による転載許可取得済み",
    ),
]


def main():
    init_db()
    print("サンプルデータを登録します...")
    with get_db() as db:
        mgr = JobManager(db)
        for i, data in enumerate(SAMPLE_JOBS, 1):
            try:
                job = mgr.create_job(data, auto_check=False)
                print(f"  [{i}] 登録OK: {data.title} → {job.id}")
                job.compliance_status = __import__("src.models", fromlist=["ComplianceStatus"]).ComplianceStatus.COMPLIANT
                job.status = __import__("src.models", fromlist=["JobStatus"]).JobStatus.ACTIVE
                from datetime import datetime, timedelta
                job.published_at = datetime.utcnow()
                job.expires_at = datetime.utcnow() + timedelta(days=30)
                db.flush()
            except Exception as e:
                print(f"  [{i}] ERROR: {e}")
        db.commit()
    print("サンプルデータ登録完了")


if __name__ == "__main__":
    main()
