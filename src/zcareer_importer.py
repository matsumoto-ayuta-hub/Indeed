"""
Zキャリア エクスポートExcel → Indeed Job Sync API への全自動パイプライン。

処理フロー:
  Excel読み込み → 列マッピング → 勤務地パース → ルールチェック
  → DB upsert → Indeed API 同期
"""
import re
import uuid
import logging
import math
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Optional

import pandas as pd
from sqlalchemy.orm import Session

from .config import settings, ACCOUNT_CONFIG
from .models import (
    Job, JobStatus, ComplianceStatus, ComplianceLog,
    JobType, ProbationaryPeriod,
    SOCIAL_INSURANCE_SUIDS, WORK_SYSTEM_SUIDS,
)
from .indeed_api import get_client

logger = logging.getLogger(__name__)

# ── マッピングテーブル ─────────────────────────────────────────────────────────

JOB_TYPE_MAP: dict[str, str] = {
    "正社員": "fulltime",
    "契約社員": "contract",
    "アルバイト・パート": "parttime",
    "アルバイト": "parttime",
    "パート": "parttime",
}

WORK_SYSTEM_MAP: dict[str, str] = {
    "固定（一般的な勤務時間）": WORK_SYSTEM_SUIDS["standard"],
    "変形労働時間制（1ヶ月単位）": WORK_SYSTEM_SUIDS["standard"],
    "変形労働時間制（1年単位）": WORK_SYSTEM_SUIDS["standard"],
    "フレックス制（コアタイムあり）": WORK_SYSTEM_SUIDS["flex"],
    "フレックス制（コアタイムなし）": WORK_SYSTEM_SUIDS["flex"],
    "裁量労働時間制（みなし労働時間制）": WORK_SYSTEM_SUIDS["discretionary_professional"],
    "その他": WORK_SYSTEM_SUIDS["standard"],
}

# 都道府県パターン（正規表現）
_PREF_RE = re.compile(
    r"^(東京都|北海道|大阪府|京都府|"
    r"(?:神奈川|埼玉|千葉|愛知|兵庫|福岡|静岡|茨城|広島|宮城|栃木|新潟|長野|"
    r"岐阜|群馬|岡山|三重|熊本|鹿児島|沖縄|長崎|滋賀|山口|愛媛|青森|岩手|"
    r"奈良|宮崎|秋田|和歌山|山形|石川|富山|大分|福島|福井|徳島|香川|高知|"
    r"島根|鳥取|山梨|佐賀)県)"
)
_CITY_RE = re.compile(
    r"^.+?[都道府県](.+?[市区町村郡])"
)


def parse_location(raw: str) -> tuple[str, str, str]:
    """勤務地文字列から (都道府県, 市区町村, 番地以降) を返す"""
    raw = str(raw).strip()
    pref_m = _PREF_RE.match(raw)
    prefecture = pref_m.group(1) if pref_m else ""
    rest = raw[len(prefecture):]

    city_m = _CITY_RE.match(raw)
    city = city_m.group(1) if city_m else ""
    address = rest[len(city):].strip()

    return prefecture, city, address


def _s(val) -> str:
    """NaN を空文字に変換"""
    if val is None or (isinstance(val, float) and math.isnan(val)):
        return ""
    return str(val).strip()


def _i(val) -> Optional[int]:
    try:
        v = float(val)
        return int(v) if not math.isnan(v) else None
    except (TypeError, ValueError):
        return None


def build_description(row: pd.Series) -> str:
    """複数のコンテンツ列を結合して説明文を構築する"""
    parts = []
    main = _s(row.get("仕事内容（仕事内容）"))
    if main:
        parts.append(main)

    appeal = _s(row.get("仕事内容（アピールポイント）"))
    if appeal:
        parts.append(f"\n【アピールポイント】\n{appeal}")

    other = _s(row.get("仕事内容（その他）"))
    if other:
        parts.append(f"\n【その他】\n{other}")

    catch = _s(row.get("求人キャッチコピー"))
    if catch:
        parts.insert(0, f"◆ {catch}\n")

    return "\n".join(parts).strip()


def row_to_job_dict(row: pd.Series, account_ids: list[str]) -> dict:
    """Excelの1行をJobモデルのフィールド辞書に変換する"""
    zcareer_id = _s(row.get("Zキャリア プラットフォーム上のid"))
    job_ref = f"ZC-{zcareer_id}" if zcareer_id else f"ZC-{uuid.uuid4().hex[:8].upper()}"

    raw_loc = _s(row.get("勤務地") or row.get("仕事内容（勤務地）"))
    prefecture, city, address = parse_location(raw_loc) if raw_loc else ("", "", "")

    jt_raw = _s(row.get("雇用形態"))
    job_type = JOB_TYPE_MAP.get(jt_raw, "fulltime")

    ws_raw = _s(row.get("勤務時間タイプ"))
    work_suid = WORK_SYSTEM_MAP.get(ws_raw, WORK_SYSTEM_SUIDS["standard"])

    # 雇用形態に応じた社会保険
    if job_type in ("fulltime", "contract"):
        si_suids = list(SOCIAL_INSURANCE_SUIDS.values())
        has_prob = ProbationaryPeriod.YES
    else:
        si_suids = [SOCIAL_INSURANCE_SUIDS["employment"], SOCIAL_INSURANCE_SUIDS["workers_comp"]]
        has_prob = ProbationaryPeriod.NO

    salary_min = _i(row.get("給与（下限）"))
    salary_max = _i(row.get("給与上限"))

    description = build_description(row)

    return dict(
        job_reference_number=job_ref,
        account_ids=account_ids,
        title=_s(row.get("職種名")),
        company_name=_s(row.get("会社名")),
        is_partner_company=True,
        prefecture=prefecture,
        city=city,
        address=address,
        job_type=job_type,
        salary_min=salary_min,
        salary_max=salary_max,
        salary_type="annual",
        salary_description=f"年収{salary_min // 10000}万〜{salary_max // 10000}万円" if salary_min and salary_max else None,
        working_hours=_s(row.get("仕事内容（勤務時間・曜日）")),
        holidays=_s(row.get("仕事内容（休暇・休日）")),
        benefits=_s(row.get("仕事内容（待遇・福利厚生）")),
        requirements=_s(row.get("仕事内容（求める人材）")),
        description=description,
        category=_s(row.get("職種カテゴリー")),
        has_probationary_period=has_prob,
        probationary_period_months=3 if has_prob == ProbationaryPeriod.YES else None,
        social_insurance_suids=si_suids,
        work_system_suids=[work_suid],
        is_republishable=True,
        source_platform="zcareer",
        apply_url=f"{settings.app_base_url}/apply/{job_ref}",
        indeed_posting_ids={},
        last_sync_at={},
        sync_errors={},
    )


# ── ルールベース コンプライアンスチェック（Claude API 不使用）────────────────────

VAGUE_TITLES = {"スタッフ募集", "メンバー募集", "仲間募集", "スタッフ", "メンバー", "社員募集"}
MIN_ANNUAL_SALARY = 2_000_000   # 年収200万円以上（最低ラインの目安）
MIN_DESC_LENGTH = 100


def fast_compliance_check(d: dict) -> tuple[ComplianceStatus, list[dict]]:
    """ルールベースで即座にチェック。APIコストゼロ。"""
    issues = []

    if not d.get("title"):
        issues.append({"severity": "critical", "field": "title", "issue": "職種名が未設定"})
    elif d["title"] in VAGUE_TITLES:
        issues.append({"severity": "critical", "field": "title", "issue": f"職種名が曖昧: {d['title']}"})

    if not d.get("prefecture") or not d.get("city"):
        issues.append({"severity": "warning", "field": "location", "issue": "勤務地の都道府県・市区町村が取得できません"})

    sal = d.get("salary_min")
    if not sal:
        issues.append({"severity": "critical", "field": "salary", "issue": "給与下限が未設定"})
    elif sal < MIN_ANNUAL_SALARY:
        issues.append({"severity": "warning", "field": "salary", "issue": f"年収{sal//10000}万円は最低ラインを下回る可能性があります"})

    desc = d.get("description") or ""
    if len(desc) < MIN_DESC_LENGTH:
        issues.append({"severity": "warning", "field": "description", "issue": f"仕事内容が短すぎます（{len(desc)}文字）"})

    if not d.get("working_hours"):
        issues.append({"severity": "warning", "field": "working_hours", "issue": "勤務時間が未設定"})
    if not d.get("holidays"):
        issues.append({"severity": "warning", "field": "holidays", "issue": "休日・休暇が未設定"})

    criticals = [i for i in issues if i["severity"] == "critical"]
    if criticals:
        return ComplianceStatus.FAILED, issues
    if issues:
        return ComplianceStatus.FIXED, issues  # 軽微な問題はそのまま掲載
    return ComplianceStatus.COMPLIANT, []


# ── メインのインポート処理 ────────────────────────────────────────────────────

@dataclass
class ImportResult:
    total: int = 0
    created: int = 0
    updated: int = 0
    skipped: int = 0
    compliance_failed: int = 0
    indeed_synced: int = 0
    indeed_errors: int = 0
    errors: list[str] = field(default_factory=list)


def import_from_excel(
    file_path: str,
    db: Session,
    account_ids: Optional[list[str]] = None,
    sync_to_indeed: bool = True,
    batch_size: int = 100,
    dry_run: bool = False,
    on_progress=None,
) -> ImportResult:
    """
    ZキャリアExcelを読み込み、DB upsert → Indeed API 同期まで一気通貫で実行する。

    Args:
        file_path:       Excelファイルパス
        db:              SQLAlchemyセッション
        account_ids:     掲載先アカウントID（デフォルト: account_partner）
        sync_to_indeed:  Indeed API に同期するか
        batch_size:      DBコミット単位
        dry_run:         DB・API への書き込みをスキップして検証のみ
        on_progress:     進捗コールバック on_progress(done, total, message)
    """
    if account_ids is None:
        account_ids = ["account_partner"]

    df = pd.read_excel(file_path, dtype=str)
    result = ImportResult(total=len(df))

    now = datetime.utcnow()
    expires = now + timedelta(days=settings.job_expiry_days)

    # Indeed API クライアントを事前準備
    clients = {
        aid: get_client(aid)
        for aid in account_ids
        if ACCOUNT_CONFIG[aid].has_credentials
    }

    for batch_start in range(0, len(df), batch_size):
        batch = df.iloc[batch_start: batch_start + batch_size]

        for _, row in batch.iterrows():
            try:
                d = row_to_job_dict(row, account_ids)
                compliance_status, issues = fast_compliance_check(d)

                if compliance_status == ComplianceStatus.FAILED:
                    result.compliance_failed += 1
                    result.errors.append(
                        f"コンプライアンス失敗: {d['title']} / {d['company_name']}: "
                        + ", ".join(i["issue"] for i in issues if i["severity"] == "critical")
                    )
                    continue

                if dry_run:
                    result.created += 1
                    continue

                # DB upsert
                ref = d["job_reference_number"]
                existing = db.query(Job).filter(Job.job_reference_number == ref).first()

                if existing:
                    for k, v in d.items():
                        if k not in ("id", "indeed_posting_ids", "last_sync_at", "sync_errors") and v:
                            setattr(existing, k, v)
                    existing.compliance_status = compliance_status
                    existing.compliance_notes = issues
                    existing.updated_at = now
                    existing.expires_at = expires
                    existing.status = JobStatus.ACTIVE
                    job = existing
                    result.updated += 1
                else:
                    job = Job(
                        id=str(uuid.uuid4()),
                        **d,
                        compliance_status=compliance_status,
                        compliance_notes=issues,
                        status=JobStatus.ACTIVE,
                        published_at=now,
                        expires_at=expires,
                    )
                    db.add(job)
                    result.created += 1

                db.flush()

                # Indeed API 同期
                if sync_to_indeed and clients:
                    _sync_job_to_indeed(job, clients, result)

            except Exception as e:
                msg = f"行処理エラー ({row.get('会社名', '?')} / {row.get('職種名', '?')}): {e}"
                result.errors.append(msg)
                logger.error(msg)

        if not dry_run:
            db.commit()

        done = min(batch_start + batch_size, len(df))
        if on_progress:
            on_progress(done, len(df), f"{done}/{len(df)} 処理済み")
        else:
            pct = done * 100 // len(df)
            print(f"  進捗: {done}/{len(df)} ({pct}%) | 新規={result.created} 更新={result.updated} 失敗={result.compliance_failed}", end="\r")

    if not dry_run:
        db.commit()

    return result


def _sync_job_to_indeed(job: Job, clients: dict, result: ImportResult):
    """Indeed API へ1件同期し、result を更新する"""
    for acc_id, client in clients.items():
        if acc_id not in (job.account_ids or []):
            continue
        try:
            existing_id = (job.indeed_posting_ids or {}).get(acc_id)
            if existing_id:
                r = client.update_job(job, existing_id)
            else:
                r = client.create_job(job)

            ids = dict(job.indeed_posting_ids or {})
            ts = dict(job.last_sync_at or {})
            errs = dict(job.sync_errors or {})

            if r.success:
                if r.indeed_posting_id:
                    ids[acc_id] = r.indeed_posting_id
                ts[acc_id] = datetime.utcnow().isoformat()
                errs.pop(acc_id, None)
                result.indeed_synced += 1
            else:
                errs[acc_id] = str(r.errors)
                result.indeed_errors += 1
                logger.warning(f"[{acc_id}] 同期失敗 {job.job_reference_number}: {r.errors}")

            job.indeed_posting_ids = ids
            job.last_sync_at = ts
            job.sync_errors = errs

        except Exception as e:
            result.indeed_errors += 1
            logger.error(f"[{acc_id}] 例外 {job.job_reference_number}: {e}")
