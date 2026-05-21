"""
Indeed Japan 掲載要件に基づくコンプライアンスチェッカー。
Claude API を使って求人票の内容を検証・自動修正する。
"""
import json
from dataclasses import dataclass, field
from typing import Optional
import anthropic
from .config import settings
from .models import Job, ComplianceStatus


SYSTEM_PROMPT = """あなたはIndeed Japan（インディード日本版）の求人掲載コンプライアンス専門家です。
有料職業紹介事業者（許可番号あり）が複数企業の求人を掲載する際の要件に精通しています。

## Indeed Japan 掲載要件チェックリスト

### 必須項目
- [ ] 職種名が具体的で明確（「スタッフ募集」「仲間募集」は不可）
- [ ] 仕事内容が具体的に記載されている（最低300文字推奨）
- [ ] 勤務地が具体的（都道府県+市区町村以上）
- [ ] 給与が具体的な金額で記載（「応相談」「要相談」のみは不可）
- [ ] 給与が最低賃金以上
- [ ] 雇用形態が明記（正社員/契約社員/パート/アルバイト/派遣/インターン等）
- [ ] 勤務時間が記載されている
- [ ] 休日・休暇が記載されている

### 禁止事項
- 差別的表現（性別・年齢・国籍による不当な制限）
- 虚偽・誇大表現（「誰でも月収100万」等）
- 求人内容と実態が異なる記載
- 採用代行・MLM・アフィリエイト等の求人
- ノルマが明示されていない歩合制求人
- 「要普通免許以上」等の必要以上の応募制限

### 有料職業紹介事業者として追加遵守事項
- 求人企業名を明記（「大手企業」等の曖昧表現は不可）
- 紹介手数料を求職者に負担させる記載は禁止
- 実際に存在する求人のみ掲載可能（架空求人禁止）
- 掲載企業の許可を得た求人のみ転載可能

あなたの役割：
1. 求人票を上記要件でチェックし、問題点をJSON形式でリストアップ
2. 問題がある場合は自動修正した説明文を提案
3. 手動レビューが必要な重大な問題を識別する
"""

COMPLIANCE_CHECK_PROMPT = """以下の求人情報をチェックして、Indeed Japan の掲載要件への適合性を評価してください。

## 求人情報
- 職種名: {title}
- 企業名: {company_name}
- 雇用形態: {job_type}
- 勤務地: {location}
- 給与: {salary}
- 勤務時間: {working_hours}
- 休日・休暇: {holidays}
- 応募資格: {requirements}
- 仕事内容:
{description}

## 指示
以下のJSON形式で回答してください：

```json
{{
  "compliance_status": "compliant" | "fixed" | "needs_manual_review" | "failed",
  "issues": [
    {{
      "severity": "critical" | "warning" | "info",
      "field": "フィールド名",
      "issue": "問題の説明",
      "fix_suggestion": "修正案（あれば）"
    }}
  ],
  "modified_description": "修正後の仕事内容（修正が必要な場合のみ）",
  "summary": "全体的なチェック結果の要約（日本語）"
}}
```

- `compliant`: 問題なし
- `fixed`: 自動修正で解決可能な軽微な問題あり
- `needs_manual_review`: 人間による確認が必要な問題あり
- `failed`: 掲載不可能な重大な問題あり

修正後の説明文には以下を必ず含めてください：
- 仕事の具体的な内容（何をするか）
- 職場環境・チームの雰囲気（あれば）
- 応募から入社までの流れ（あれば）
- 原文にある重要情報はすべて保持すること
"""


@dataclass
class ComplianceResult:
    status: ComplianceStatus
    issues: list[dict] = field(default_factory=list)
    modified_description: Optional[str] = None
    summary: str = ""
    tokens_used: int = 0
    model_used: str = ""


class ComplianceChecker:
    def __init__(self):
        self.client = anthropic.Anthropic(api_key=settings.anthropic_api_key)

    def _format_salary(self, job: Job) -> str:
        if job.salary_description:
            return job.salary_description
        if job.salary_min and job.salary_max:
            unit = {"monthly": "万円/月", "hourly": "円/時間", "annual": "万円/年"}.get(
                job.salary_type, "円"
            )
            return f"{job.salary_min // 10000}〜{job.salary_max // 10000}{unit}"
        if job.salary_min:
            unit = {"monthly": "万円/月〜", "hourly": "円/時間〜", "annual": "万円/年〜"}.get(
                job.salary_type, "円〜"
            )
            return f"{job.salary_min // 10000}{unit}"
        return "未設定"

    def _format_location(self, job: Job) -> str:
        parts = [job.prefecture, job.city]
        if job.address:
            parts.append(job.address)
        loc = " ".join(p for p in parts if p)
        if job.is_remote:
            loc += f"（{job.remote_type}）"
        return loc or "未設定"

    def _job_type_ja(self, job: Job) -> str:
        mapping = {
            "fulltime": "正社員",
            "parttime": "パート・アルバイト",
            "contract": "契約社員",
            "temporary": "派遣社員",
            "internship": "インターンシップ",
            "freelance": "業務委託",
        }
        return mapping.get(job.job_type.value if hasattr(job.job_type, "value") else job.job_type, "その他")

    def check(self, job: Job) -> ComplianceResult:
        prompt = COMPLIANCE_CHECK_PROMPT.format(
            title=job.title,
            company_name=job.company_name,
            job_type=self._job_type_ja(job),
            location=self._format_location(job),
            salary=self._format_salary(job),
            working_hours=job.working_hours or "未設定",
            holidays=job.holidays or "未設定",
            requirements=job.requirements or "特になし",
            description=job.description_modified or job.description,
        )

        message = self.client.messages.create(
            model=settings.claude_model,
            max_tokens=2048,
            system=SYSTEM_PROMPT,
            messages=[{"role": "user", "content": prompt}],
        )

        raw = message.content[0].text
        tokens = message.usage.input_tokens + message.usage.output_tokens

        # JSON部分を抽出
        try:
            start = raw.find("{")
            end = raw.rfind("}") + 1
            data = json.loads(raw[start:end])
        except (json.JSONDecodeError, ValueError):
            return ComplianceResult(
                status=ComplianceStatus.NEEDS_MANUAL_REVIEW,
                summary="レスポンスのパースに失敗しました。手動確認が必要です。",
                tokens_used=tokens,
                model_used=settings.claude_model,
            )

        status_map = {
            "compliant": ComplianceStatus.COMPLIANT,
            "fixed": ComplianceStatus.FIXED,
            "needs_manual_review": ComplianceStatus.NEEDS_MANUAL_REVIEW,
            "failed": ComplianceStatus.FAILED,
        }

        return ComplianceResult(
            status=status_map.get(data.get("compliance_status", "needs_manual_review"),
                                  ComplianceStatus.NEEDS_MANUAL_REVIEW),
            issues=data.get("issues", []),
            modified_description=data.get("modified_description"),
            summary=data.get("summary", ""),
            tokens_used=tokens,
            model_used=settings.claude_model,
        )
