# Slack 動画批評ボット セットアップ手順書

Araki Ryuki / Goshi Reira から Slack に動画が送られるたびに、TikTok 批評チャンネル計画書に基づく批評案を Claude が自動生成してスレッド返信するボットのセットアップ手順です。

---

## 全体の流れ

```
① Slack App 作成
② .env 設定
③ サーバー起動
④ Slack App にURL登録して完了
```

---

## Step 1: Slack App を作成する

### 1-1. アプリを新規作成

1. [https://api.slack.com/apps](https://api.slack.com/apps) にアクセス
2. **「Create New App」** → **「From scratch」** を選択
3. App Name（例: `批評ボット`）と対象ワークスペースを入力して作成

### 1-2. Bot の権限を設定

左メニュー **「OAuth & Permissions」** → **「Scopes」** の **Bot Token Scopes** に以下を追加

| Scope | 用途 |
|---|---|
| `chat:write` | チャンネルへのメッセージ投稿 |
| `files:read` | 動画ファイルの情報取得 |

### 1-3. イベント購読を設定

左メニュー **「Event Subscriptions」** をONにする

**「Subscribe to bot events」** に以下を追加

| Event | 用途 |
|---|---|
| `message.channels` | パブリックチャンネルの発言を受信 |
| `message.groups` | プライベートチャンネルの発言を受信（必要な場合） |

> Request URL はサーバー起動後に設定します（Step 4）

### 1-4. アプリをワークスペースにインストール

左メニュー **「OAuth & Permissions」** → **「Install to Workspace」** → 許可

インストール後に表示される **Bot User OAuth Token（`xoxb-...`）** をコピーしておく

### 1-5. Signing Secret を確認

左メニュー **「Basic Information」** → **「App Credentials」** → **Signing Secret** をコピー

---

## Step 2: .env ファイルを設定する

プロジェクトルートの `.env` ファイルを開き、以下を入力する

```env
# Anthropic API
ANTHROPIC_API_KEY=sk-ant-...

# Slack 批評ボット
SLACK_BOT_TOKEN=xoxb-...           # Step 1-4 でコピーした Bot Token
SLACK_SIGNING_SECRET=...           # Step 1-5 でコピーした Signing Secret

# 批評案を投稿するチャンネルID（動画が届いたチャンネルとは別に通知したい場合）
# 空のままにすると、動画が届いたチャンネルのスレッドのみに返信します
SLACK_CRITIQUE_CHANNEL_ID=

# 動画を送ってくるメンバーの Slack ユーザーID（取得方法は下記参照）
ARAKI_RYUKI_SLACK_USER_ID=
GOSHI_REIRA_SLACK_USER_ID=
```

> 両方のユーザーIDが空の場合、チャンネル内の全員の動画メッセージに反応します

### Slack ユーザーID の調べ方

1. Slack でユーザーのプロフィールを開く
2. 「…」メニュー → **「メンバーIDをコピー」** を選択
3. `U0123456789` 形式の文字列が取得できる

---

## Step 3: サーバーを起動する

```bash
# 依存ライブラリのインストール（初回のみ）
pip install -r requirements.txt

# サーバー起動
uvicorn src.api:app --reload --port 8000
```

起動後、以下のURLでAPIが動いていることを確認

```
http://localhost:8000/docs
```

### ローカル環境で試す場合（ngrok を使う）

Slack は外部からアクセスできる URL を必要とするため、ngrok でトンネルを作る

```bash
# ngrok のインストール（未インストールの場合）
brew install ngrok  # macOS
# または https://ngrok.com/download

# トンネル作成
ngrok http 8000
```

表示される `https://xxxx.ngrok.io` の URL を控えておく

---

## Step 4: Slack App に URL を登録して完了

1. [https://api.slack.com/apps](https://api.slack.com/apps) でアプリを開く
2. 左メニュー **「Event Subscriptions」** → Request URL に入力

```
https://your-domain.com/slack/events
# ローカルの場合:
https://xxxx.ngrok.io/slack/events
```

3. URLを入力すると Slack が自動で疎通確認を行い、**「Verified ✓」** と表示されれば完了
4. **「Save Changes」** をクリック

---

## 動作確認

設定が完了したら、Slack で対象チャンネルに以下のいずれかを投稿してテストする

- TikTok の URL を貼り付ける（例: `https://www.tiktok.com/@...`）
- 動画ファイル（.mp4 / .mov）を添付する

数秒後に批評ボットがスレッド返信で批評案を投稿すれば成功

---

## トラブルシューティング

| 症状 | 原因 | 対処 |
|---|---|---|
| Slack に返信が来ない | ユーザーID が間違っている | `.env` の `ARAKI_RYUKI_SLACK_USER_ID` を再確認 |
| `Invalid Slack signature` エラー | Signing Secret が間違っている | `.env` の `SLACK_SIGNING_SECRET` を再確認 |
| `not_in_channel` エラー | ボットがチャンネルに未参加 | チャンネルでボットをメンション or `/invite @批評ボット` |
| URL Verified にならない | サーバーが起動していない | `uvicorn` の起動を確認、ngrok のURLを再確認 |

---

## 批評案のフォーマット

ボットはPDFの「黄金の台本テンプレート」に従って以下の構成で批評案を生成します

```
【ツカミ】0〜3秒
  スクロールを止める強烈な問いかけ

【事実提示】3〜15秒
  状況の要約（知らない人にも分かるよう）

【批評】15〜45秒
  世論の代弁 + マーケ・演出視点のインサイト
  【撮影者の声】相槌を1〜2箇所挿入

【問いかけ】45〜60秒
  賛否両論を誘うコメント促進の締め
```
