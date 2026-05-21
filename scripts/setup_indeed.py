"""
Indeed Partner Console セットアップ支援スクリプト。

このスクリプトが実行すること:
1. .env の設定状況を診断
2. Indeed API への疎通テスト（クレデンシャルが設定済みの場合）
3. 登録に必要な情報を表示

使い方:
  python scripts/setup_indeed.py
  python scripts/setup_indeed.py --test-auth   # 認証テストのみ
  python scripts/setup_indeed.py --write-env   # .env を対話的に更新
"""
import sys
import os
import argparse

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))


PARTNER_CONSOLE_URL = "https://partners.indeed.com/"
PARTNER_DOCS_URL = "https://docs.indeed.com/job-sync-api"
PARTNER_JAPAN_URL = "https://docs.indeed.com/job-sync-api/for-japan-partners/posting-guidelines"

REGISTRATION_STEPS = """
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  Indeed Partner Console 登録手順（3アカウント分）
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

【Step 1】Indeed パートナー申請
  URL: https://partners.indeed.com/
  - "Partner with Indeed" または "Get Started" をクリック
  - Company type: "Staffing/Recruiting Agency" を選択
  - 事業種別: "Third-Party Recruiter" （有料職業紹介事業者）
  - 許可番号: 13-ユ-318960 を記載

【Step 2】各アカウントの OAuth クレデンシャル取得
  - Partner Console にログイン後、Applications → Create App
  - アカウントごとに App を1つ作成（計3つ）:
      App 1: "キャリアジャパン自社採用"     → account_self
      App 2: "キャリアジャパンインターン"   → account_intern
      App 3: "キャリアジャパンパートナー"   → account_partner
  - 各 App で Client ID と Client Secret を発行

【Step 3】.env にクレデンシャルを設定
  ACCOUNT_SELF_CLIENT_ID=<App1のClient ID>
  ACCOUNT_SELF_CLIENT_SECRET=<App1のClient Secret>

  ACCOUNT_INTERN_CLIENT_ID=<App2のClient ID>
  ACCOUNT_INTERN_CLIENT_SECRET=<App2のClient Secret>

  ACCOUNT_PARTNER_CLIENT_ID=<App3のClient ID>
  ACCOUNT_PARTNER_CLIENT_SECRET=<App3のClient Secret>

【Step 4】疎通テスト
  python scripts/setup_indeed.py --test-auth

【参考ドキュメント】
  Job Sync API ガイド: https://docs.indeed.com/job-sync-api
  日本向け掲載ガイドライン: https://docs.indeed.com/job-sync-api/for-japan-partners/posting-guidelines
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
"""


def check_env():
    """現在の .env 設定状況を診断する"""
    from src.config import settings, ACCOUNT_CONFIG

    print("\n【.env 設定状況】")
    print(f"  ANTHROPIC_API_KEY   : {'✅ 設定済み' if settings.anthropic_api_key and not settings.anthropic_api_key.startswith('sk-ant-...') else '❌ 未設定'}")
    print(f"  AGENCY_LICENSE_NUMBER: {settings.agency_license_number}")
    print(f"  AGENCY_NAME          : {settings.agency_name}")
    print(f"  APP_BASE_URL         : {settings.app_base_url}")
    print()

    all_ok = True
    for acc_id, cfg in ACCOUNT_CONFIG.items():
        has = cfg.has_credentials
        print(f"  {acc_id}:")
        print(f"    CLIENT_ID    : {'✅ 設定済み' if cfg.client_id else '❌ 未設定'}")
        print(f"    CLIENT_SECRET: {'✅ 設定済み' if cfg.client_secret else '❌ 未設定'}")
        if not has:
            all_ok = False
    print()
    return all_ok


def test_auth():
    """各アカウントの OAuth 認証テスト"""
    import httpx
    from src.config import settings, ACCOUNT_CONFIG

    print("\n【OAuth 認証テスト】")
    for acc_id, cfg in ACCOUNT_CONFIG.items():
        if not cfg.has_credentials:
            print(f"  {acc_id}: ⏭ スキップ（クレデンシャル未設定）")
            continue
        try:
            resp = httpx.post(
                settings.indeed_token_url,
                data={
                    "grant_type": "client_credentials",
                    "client_id": cfg.client_id,
                    "client_secret": cfg.client_secret,
                },
                headers={"Content-Type": "application/x-www-form-urlencoded"},
                timeout=10,
            )
            if resp.status_code == 200:
                data = resp.json()
                expires = data.get("expires_in", "?")
                print(f"  {acc_id}: ✅ 認証成功（トークン有効期間: {expires}秒）")
            else:
                print(f"  {acc_id}: ❌ 認証失敗 HTTP {resp.status_code}: {resp.text[:200]}")
        except Exception as e:
            print(f"  {acc_id}: ❌ 接続エラー: {e}")
    print()


def write_env_interactive():
    """対話形式で .env ファイルを更新する"""
    env_path = ".env"
    if not os.path.exists(env_path):
        import shutil
        shutil.copy(".env.example", env_path)
        print(f".env.example を .env にコピーしました")

    with open(env_path) as f:
        content = f.read()

    print("\n【.env 対話式設定】（Enterで現在値を保持）")

    def ask(key: str, current_val: str, description: str) -> str:
        prompt = f"  {description}\n  {key} [{current_val or '未設定'}]: "
        val = input(prompt).strip()
        return val if val else current_val

    from src.config import settings, ACCOUNT_CONFIG

    updates = {
        "ANTHROPIC_API_KEY": ask("ANTHROPIC_API_KEY", settings.anthropic_api_key, "Anthropic APIキー"),
        "APP_BASE_URL": ask("APP_BASE_URL", settings.app_base_url, "公開ドメイン（例: https://jobs.careerjapan.co）"),
    }
    for acc_id, cfg in ACCOUNT_CONFIG.items():
        env_prefix = acc_id.upper().replace("ACCOUNT_", "ACCOUNT_").replace("_", "_")
        label = cfg.description
        updates[f"ACCOUNT_{acc_id.upper().split('_')[1]}_CLIENT_ID"] = ask(
            f"ACCOUNT_{acc_id.upper().split('_')[1]}_CLIENT_ID",
            cfg.client_id,
            f"[{label}] Client ID（Partner Console から取得）",
        )
        updates[f"ACCOUNT_{acc_id.upper().split('_')[1]}_CLIENT_SECRET"] = ask(
            f"ACCOUNT_{acc_id.upper().split('_')[1]}_CLIENT_SECRET",
            cfg.client_secret,
            f"[{label}] Client Secret",
        )

    for key, value in updates.items():
        if f"{key}=" in content:
            import re
            content = re.sub(rf"^{key}=.*$", f"{key}={value}", content, flags=re.MULTILINE)
        else:
            content += f"\n{key}={value}\n"

    with open(env_path, "w") as f:
        f.write(content)
    print("\n.env を更新しました。")


def main():
    parser = argparse.ArgumentParser(description="Indeed パートナー設定ツール")
    parser.add_argument("--test-auth", action="store_true", help="OAuth 認証テストのみ実行")
    parser.add_argument("--write-env", action="store_true", help=".env を対話的に設定")
    args = parser.parse_args()

    if args.write_env:
        write_env_interactive()
        return

    print(REGISTRATION_STEPS)
    all_ok = check_env()

    if args.test_auth or all_ok:
        test_auth()
    else:
        print("クレデンシャルが未設定のアカウントがあります。")
        print("上記の登録手順に従い、.env に設定してから再実行してください。")
        print("  python scripts/setup_indeed.py --write-env")


if __name__ == "__main__":
    main()
