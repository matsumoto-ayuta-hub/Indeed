"""
動作確認用サンプル求人データを登録するスクリプト。
Indeed API への実際の投稿は行わない（クレデンシャル未設定でも動作する）。
"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from src.database import init_db, get_db
from src.models import JobCreate, JobType, ProbationaryPeriod, SOCIAL_INSURANCE_SUIDS, WORK_SYSTEM_SUIDS
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
        working_hours="09:00〜18:00（フレックスタイム制、コアタイム10:00〜15:00）",
        holidays="完全週休2日制（土日）、祝日、年末年始、有給休暇",
        benefits="交通費全額支給、社会保険完備、リモートワーク可、技術書購入補助",
        requirements="Python/Java/GoいずれかのWebバックエンド開発経験3年以上",
        description="Webアプリケーションのバックエンド開発を担当していただきます。マイクロサービスアーキテクチャでの開発経験者を歓迎します。チームは10名構成で、アジャイル開発を採用しています。",
        category="IT・エンジニア",
        has_probationary_period=ProbationaryPeriod.YES,
        probationary_period_months=3,
        social_insurance_suids=list(SOCIAL_INSURANCE_SUIDS.values()),
        work_system_suids=[WORK_SYSTEM_SUIDS["flex"]],
        is_republishable=False,
    ),
    # インターン
    JobCreate(
        title="Webマーケティングインターン（有給）",
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
        working_hours="週2〜3日、1日3〜8時間（授業優先でシフト調整可）",
        holidays="シフト制",
        benefits="交通費全額支給、インターン修了証発行、就活サポートあり",
        requirements="大学生・大学院生（学年不問）、マーケティングに関心がある方",
        description="SNSマーケティングやコンテンツ制作を通じて実践的なスキルを習得できます。業務内容：SNS運用補助、記事作成、データ分析レポート作成。正社員登用実績あり。",
        category="マーケティング",
        has_probationary_period=ProbationaryPeriod.NO,
        social_insurance_suids=[SOCIAL_INSURANCE_SUIDS["employment"], SOCIAL_INSURANCE_SUIDS["workers_comp"]],
        work_system_suids=[WORK_SYSTEM_SUIDS["shift"]],
        is_republishable=False,
    ),
    # 提携先企業求人（転載）
    JobCreate(
        title="法人営業（SaaSソリューション）",
        company_name="株式会社テクノソリューション",
        account_ids=["account_partner", "account_self"],
        is_partner_company=True,
        prefecture="大阪府",
        city="大阪市北区",
        postal_code="530-0001",
        address="梅田2-2-2",
        job_type=JobType.FULLTIME,
        salary_min=3500000,
        salary_max=6000000,
        salary_type="annual",
        working_hours="09:00〜18:00（フレックス制、コアタイム10:00〜15:00）",
        holidays="完全週休2日制（土日祝）、有給休暇20日",
        benefits="インセンティブあり、各種社会保険、資格取得支援",
        requirements="法人営業経験1年以上。SaaS製品の営業経験者優遇",
        description="中小〜中堅企業向けの業務効率化SaaSソリューションの提案営業をお任せします。既存顧客への深耕営業と新規開拓を組み合わせた業務内容です。1人あたりの担当社数は30〜50社程度。",
        category="営業",
        has_probationary_period=ProbationaryPeriod.YES,
        probationary_period_months=3,
        social_insurance_suids=list(SOCIAL_INSURANCE_SUIDS.values()),
        work_system_suids=[WORK_SYSTEM_SUIDS["flex"]],
        source_url="https://example-partner.com/jobs/001",
        is_republishable=True,
        republish_permission="書面による転載許可取得済み（2026-04-01）",
    ),
]


def main():
    init_db()
    print("サンプルデータを登録します（コンプライアンスチェックはスキップ）...")
    with get_db() as db:
        mgr = JobManager(db)
        for i, data in enumerate(SAMPLE_JOBS, 1):
            try:
                job = mgr.create_job(data, auto_check=False)
                from src.models import ComplianceStatus, JobStatus
                from datetime import datetime, timedelta
                job.compliance_status = ComplianceStatus.COMPLIANT
                job.status = JobStatus.ACTIVE
                job.published_at = datetime.utcnow()
                job.expires_at = datetime.utcnow() + timedelta(days=30)
                db.flush()
                print(f"  [{i}] 登録OK: {data.title} / {data.company_name} → {job.id}")
            except Exception as e:
                print(f"  [{i}] ERROR: {e}")
        db.commit()
    print("完了。次は python scripts/setup_indeed.py で Indeed 接続を設定してください。")


if __name__ == "__main__":
    main()
