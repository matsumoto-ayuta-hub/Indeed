"""
Indeed Japan XML Job Feed ジェネレーター。
アカウントごとに求人フィードを生成してファイルに書き出す。
"""
import os
from datetime import datetime
from typing import List
from xml.etree.ElementTree import Element, SubElement, tostring
from xml.dom import minidom
from sqlalchemy.orm import Session

from .config import settings, ACCOUNT_CONFIG
from .models import Job, JobStatus, ComplianceStatus, FeedLog


def _cdata(parent: Element, tag: str, text: str) -> SubElement:
    el = SubElement(parent, tag)
    el.text = text or ""
    return el


def _format_date(dt: datetime) -> str:
    return dt.strftime("%a, %d %b %Y %H:%M:%S GMT") if dt else ""


def _salary_text(job: Job) -> str:
    if job.salary_description:
        return job.salary_description
    if job.salary_min and job.salary_max:
        units = {"monthly": "万円/月", "hourly": "円/時間", "annual": "万円/年"}
        u = units.get(job.salary_type or "monthly", "円")
        lo = job.salary_min // 10000 if job.salary_type in ("monthly", "annual") else job.salary_min
        hi = job.salary_max // 10000 if job.salary_type in ("monthly", "annual") else job.salary_max
        return f"{lo}〜{hi}{u}"
    if job.salary_min:
        units = {"monthly": "万円/月〜", "hourly": "円/時間〜", "annual": "万円/年〜"}
        u = units.get(job.salary_type or "monthly", "円〜")
        lo = job.salary_min // 10000 if job.salary_type in ("monthly", "annual") else job.salary_min
        return f"{lo}{u}"
    return ""


def _build_description(job: Job) -> str:
    """Indeed表示用の詳細説明を組み立てる（XML内の description フィールド）"""
    parts = []
    description = job.description_modified or job.description
    parts.append(description)

    if job.working_hours:
        parts.append(f"\n【勤務時間】\n{job.working_hours}")
    if job.holidays:
        parts.append(f"\n【休日・休暇】\n{job.holidays}")
    if job.requirements:
        parts.append(f"\n【応募資格】\n{job.requirements}")
    if job.benefits:
        parts.append(f"\n【待遇・福利厚生】\n{job.benefits}")

    # 有料職業紹介事業者として必須の注記
    parts.append(
        f"\n【採用担当】\n{settings.agency_name}（有料職業紹介事業 許可番号：{settings.agency_license_number}）"
    )
    return "\n".join(parts)


def _job_type_indeed(job_type: str) -> str:
    mapping = {
        "fulltime": "fulltime",
        "parttime": "parttime",
        "contract": "contract",
        "temporary": "temporary",
        "internship": "internship",
        "freelance": "other",
    }
    return mapping.get(job_type, "other")


def build_job_element(root: Element, job: Job, apply_base_url: str):
    job_el = SubElement(root, "job")

    desc = _build_description(job)
    salary = _salary_text(job)

    _cdata(job_el, "title", job.title)
    _cdata(job_el, "date", _format_date(job.published_at or job.created_at))
    _cdata(job_el, "referencenumber", job.job_reference_number or job.id)
    _cdata(job_el, "url", job.apply_url or f"{apply_base_url}/apply/{job.id}")
    _cdata(job_el, "company", job.company_name)
    _cdata(job_el, "city", job.city or "")
    _cdata(job_el, "state", job.prefecture or "")
    _cdata(job_el, "country", "JP")
    if job.postal_code:
        _cdata(job_el, "postalcode", job.postal_code.replace("-", ""))
    _cdata(job_el, "description", desc)
    if salary:
        _cdata(job_el, "salary", salary)
    _cdata(job_el, "jobtype", _job_type_indeed(
        job.job_type.value if hasattr(job.job_type, "value") else job.job_type
    ))
    if job.category:
        _cdata(job_el, "category", job.category)
    if job.remote_type and job.remote_type != "onsite":
        _cdata(job_el, "remotetype", job.remote_type)
    if job.expires_at:
        _cdata(job_el, "expirationdate", _format_date(job.expires_at))


def generate_feed_for_account(account_id: str, db: Session) -> str:
    """指定アカウントの求人フィードXMLを生成してファイルパスを返す"""
    config = ACCOUNT_CONFIG[account_id]

    # 掲載対象の求人を取得
    query = db.query(Job).filter(
        Job.status == JobStatus.ACTIVE,
        Job.compliance_status.in_([ComplianceStatus.COMPLIANT, ComplianceStatus.FIXED]),
    )

    jobs: List[Job] = [
        j for j in query.all()
        if account_id in (j.account_ids or [])
    ]

    # アカウント設定に基づくフィルタ
    filtered = []
    for job in jobs:
        jt = job.job_type.value if hasattr(job.job_type, "value") else job.job_type
        allowed_types = config.get("allowed_job_types")
        if allowed_types and jt not in allowed_types:
            continue
        if not config["allow_partner_jobs"] and job.is_partner_company:
            continue
        if not config["allow_own_jobs"] and not job.is_partner_company:
            continue
        filtered.append(job)

    # 上限適用
    filtered = filtered[: config["max_jobs"]]

    # XML構築
    root = Element("source")
    _cdata(root, "publisher", config["name"])
    _cdata(root, "publisherurl", settings.app_base_url)
    _cdata(root, "lastBuildDate", _format_date(datetime.utcnow()))

    for job in filtered:
        build_job_element(root, job, settings.app_base_url)

    xml_str = minidom.parseString(tostring(root, encoding="unicode")).toprettyxml(indent="  ")
    # minidom が挿入する XML 宣言を UTF-8 付きに置換
    xml_str = xml_str.replace(
        '<?xml version="1.0" ?>',
        '<?xml version="1.0" encoding="UTF-8"?>',
    )

    os.makedirs("feeds", exist_ok=True)
    file_path = f"feeds/{account_id}.xml"
    with open(file_path, "w", encoding="utf-8") as f:
        f.write(xml_str)

    # ログ記録
    log = FeedLog(
        account_id=account_id,
        job_count=len(filtered),
        file_path=file_path,
        success=True,
    )
    db.add(log)
    db.commit()

    return file_path


def generate_all_feeds(db: Session) -> dict[str, str]:
    from .config import ACCOUNT_IDS
    results = {}
    for account_id in ACCOUNT_IDS:
        try:
            path = generate_feed_for_account(account_id, db)
            results[account_id] = path
        except Exception as e:
            log = FeedLog(account_id=account_id, success=False, error_message=str(e))
            db.add(log)
            db.commit()
            results[account_id] = f"ERROR: {e}"
    return results
