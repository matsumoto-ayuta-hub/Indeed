"""
Slackでのビデオ受信を検知し、TikTok批評チャンネル計画書に基づく批評案を
Claude APIで自動生成してSlackに投稿する。
"""
import hashlib
import hmac
import re
import time
from typing import Optional

import anthropic
import httpx

from .config import settings

# ── プロンプト ─────────────────────────────────────────────────────────────────

CRITIQUE_SYSTEM_PROMPT = """あなたはTikTok批評動画チャンネルの台本ライターです。
送られてきた動画の情報をもとに、視聴者のコメント・共感・尊敬を引き出す批評案を作成してください。

## 批評の5大ルール（ただのアンチにならないために）

1. **人格否定ではなく「言動・演出」を批評する**
   「この人は性格が悪い」ではなく「この言動はターゲット層の感情をはき違えていて損をしています」と
   冷静・論理的に語る。

2. **主語を「世間・視聴者・ファン」にして代弁する**
   「俺が不快」ではなく「視聴者が求めている盛り上がりとズレてしまっている」という表現で世論の味方をつくる。

3. **ラストで「プロとしてのリスペクト」を添える**
   批評の後に「でも、この演出を貫く姿勢はエンタメのプロとして超重要ですよね」など一言添えて
   動画全体の知性を担保する。

4. **断言を避けてコメント欄に「判断の余白」を残す**
   「こいつが悪い」で終わらせず「皆さんはこのやり方、アリだと思いますか？」と問いかけて
   コメント欄の激論を誘発する。

## バズを狙うシーン分析の視点

- **賛否が割れる「境界線」**: 全員賛成でも全員反対でもないギリギリのシーン
- **主役より「ヒール・脇役」**: 人間味と考察の深みが出る人物に注目する
- **「暗黙のルール」を破る瞬間**: コミュニティのマナーやタブーに触れた場面

## 出力フォーマット（黄金の台本テンプレート 30〜60秒想定）

### 🎬 批評案タイトル
（視聴者の目を引く、賛否が割れそうなタイトル）

---

**【ツカミ】0〜3秒**
スクロールの手を止める強烈な問いかけ。「ぶっちゃけ〜じゃないですか？」スタイル。

**【事実提示】3〜15秒**
何が起きたかを知らない人でも理解できる状況の要約。SNS上の反応も一言触れる。

**【批評】15〜45秒**
世論の代弁＋裏側の構造を暴く分析。マーケティング・演出視点の独自インサイトを1点必ず入れる。
「知性」と「呆れ」を同居させ、感情的でなくトーンの強弱で説得力をコントロールする。

　　*【撮影者の声】「〜ってことですか？」*（視聴者代弁の相槌を1〜2箇所挿入）

**【問いかけ】45〜60秒**
賛否両論を誘うコメント促進の問いかけで締める。「みんなはどう思う？コメントで教えて」
"""

CRITIQUE_USER_PROMPT = """以下の動画情報をもとに批評案を作成してください。

## 送られてきた動画の情報

{video_info}

批評の5大ルール・黄金の台本テンプレートに従い、視聴者が共感・尊敬でき、
コメント欄が活発になる批評案を日本語で作成してください。
"""

_TIKTOK_URL_RE = re.compile(
    r"https?://(?:www\.)?tiktok\.com/\S+|https?://vm\.tiktok\.com/\S+"
)
_OG_TITLE_PATTERNS = [
    r'<meta[^>]+property=["\']og:title["\'][^>]+content=["\']([^"\']+)["\']',
    r'<meta[^>]+content=["\']([^"\']+)["\'][^>]+property=["\']og:title["\']',
    r"<title>([^<]+)</title>",
]


class SlackCritic:
    def __init__(self) -> None:
        self.anthropic_client = anthropic.Anthropic(api_key=settings.anthropic_api_key)

    # ── Slack署名検証 ──────────────────────────────────────────────────────────

    def verify_signature(self, body: bytes, timestamp: str, signature: str) -> bool:
        """Slack署名（v0=...）を検証してリクエストの正当性を確認する。"""
        try:
            if abs(time.time() - int(timestamp)) > 300:
                return False
        except (ValueError, TypeError):
            return False
        base = f"v0:{timestamp}:{body.decode('utf-8')}"
        mac = hmac.new(
            settings.slack_signing_secret.encode("utf-8"),
            base.encode("utf-8"),
            hashlib.sha256,
        )
        expected = f"v0={mac.hexdigest()}"
        return hmac.compare_digest(expected, signature)

    # ── TikTok URL からメタ情報を取得 ────────────────────────────────────────────

    def _fetch_og_title(self, url: str) -> Optional[str]:
        try:
            with httpx.Client(follow_redirects=True, timeout=5.0) as client:
                resp = client.get(
                    url, headers={"User-Agent": "Mozilla/5.0 (compatible; CriticBot/1.0)"}
                )
            if resp.status_code != 200:
                return None
            for pattern in _OG_TITLE_PATTERNS:
                m = re.search(pattern, resp.text, re.IGNORECASE)
                if m:
                    return m.group(1).strip()
        except Exception:
            pass
        return None

    # ── 動画情報の組み立て ─────────────────────────────────────────────────────

    def _build_video_info(self, event: dict) -> Optional[str]:
        text: str = event.get("text", "")
        files: list = event.get("files", [])
        video_parts: list[str] = []  # 動画コンテンツ（URL・ファイル）の情報
        extra_parts: list[str] = []  # 補足テキスト

        # TikTok URL を抽出してタイトル取得を試みる
        for url in _TIKTOK_URL_RE.findall(text):
            video_parts.append(f"TikTok URL: {url}")
            title = self._fetch_og_title(url)
            if title:
                video_parts.append(f"動画タイトル: {title}")

        # 添付動画ファイルの情報
        video_exts = (".mp4", ".mov", ".avi", ".webm", ".m4v")
        for f in files:
            mime: str = f.get("mimetype", "")
            name: str = f.get("name", "")
            title: str = f.get("title", name)
            if "video" in mime or name.lower().endswith(video_exts):
                video_parts.append(f"動画ファイル名: {title}")

        # 動画コンテンツがない場合はスキップ
        if not video_parts:
            return None

        # URL を除いたメッセージ本文（補足として追加）
        clean_text = _TIKTOK_URL_RE.sub("", text).strip()
        if clean_text:
            extra_parts.append(f"メッセージ: {clean_text}")

        return "\n".join(video_parts + extra_parts)

    # ── Claude API で批評生成 ──────────────────────────────────────────────────

    def generate_critique(self, video_info: str) -> str:
        message = self.anthropic_client.messages.create(
            model=settings.claude_model,
            max_tokens=1500,
            system=CRITIQUE_SYSTEM_PROMPT,
            messages=[{
                "role": "user",
                "content": CRITIQUE_USER_PROMPT.format(video_info=video_info),
            }],
        )
        return message.content[0].text

    # ── Slack へ投稿 ────────────────────────────────────────────────────────────

    def post_to_slack(
        self,
        text: str,
        channel: str,
        thread_ts: Optional[str] = None,
    ) -> bool:
        payload: dict = {"channel": channel, "text": text}
        if thread_ts:
            payload["thread_ts"] = thread_ts
        try:
            with httpx.Client(timeout=10.0) as client:
                resp = client.post(
                    "https://slack.com/api/chat.postMessage",
                    headers={"Authorization": f"Bearer {settings.slack_bot_token}"},
                    json=payload,
                )
            return resp.json().get("ok", False)
        except Exception:
            return False

    # ── メインハンドラ ─────────────────────────────────────────────────────────

    def handle_video_message(self, event: dict) -> bool:
        """
        Araki Ryuki さんからの動画メッセージを受け取り、
        批評案を生成してスレッド返信で投稿する。
        """
        user_id: str = event.get("user", "")
        # ARAKI_RYUKI_SLACK_USER_ID が設定されている場合はその人のみ処理
        if settings.araki_ryuki_slack_user_id and user_id != settings.araki_ryuki_slack_user_id:
            return False

        video_info = self._build_video_info(event)
        if not video_info:
            return False

        critique = self.generate_critique(video_info)
        header = "*📝 批評案（Araki Ryuki さんの動画より）*\n"
        source_channel: str = event.get("channel", settings.slack_critique_channel_id)
        thread_ts: Optional[str] = event.get("ts")

        # 元メッセージのチャンネルにスレッド返信
        ok = self.post_to_slack(header + critique, channel=source_channel, thread_ts=thread_ts)

        # 別途批評チャンネルが設定されていれば、そちらにも投稿
        critique_ch = settings.slack_critique_channel_id
        if critique_ch and critique_ch != source_channel:
            self.post_to_slack(header + critique, channel=critique_ch)

        return ok
