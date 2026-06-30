/**
 * 05_adcost_indeed.gs
 * Indeed 広告費の月次自動取得 → AdCost_Monthly シートへ書き込み
 *
 * ── 前提 ──────────────────────────────────────────────────────────────────
 * Indeed の広告費データは Job Sync API (求人投稿) とは別の
 * Campaign Management API (Advertiser API) から取得します。
 *
 * 認証: 同じ OAuth2 Client Credentials を流用
 *   スクリプトプロパティ:
 *     INDEED_CLIENT_ID     … Indeed OAuth クライアントID
 *     INDEED_CLIENT_SECRET … Indeed OAuth クライアントシークレット
 *     INDEED_EMPLOYER_ID   … Indeed 管理画面の雇用主ID（URLから確認）
 *
 * ── 初回セットアップ ──────────────────────────────────────────────────────
 * 1. GASエディタ → プロジェクトのプロパティ → スクリプトプロパティ に上記3つを登録
 * 2. setupIndeedCostTrigger() を実行してトリガーを登録
 * 3. fetchIndeedMonthlyCost() を手動実行して動作確認
 *
 * ── API エンドポイントについて ───────────────────────────────────────────
 * Indeed Japan の広告費 API は非公開の場合があります。
 * 下記の SPEND_API_URL が 404 を返す場合は、Indeed Japan 担当者に
 * 「Advertiser Reporting API」または「Campaign Spend API」のエンドポイントを確認してください。
 * その間は手動入力で運用し、エンドポイント確認後に差し替えてください。
 */

var INDEED_TOKEN_URL = 'https://apis.indeed.com/oauth/v2/tokens';
var INDEED_SPEND_URL = 'https://apis.indeed.com/ads/v1/employer/{employerId}/campaigns/spend';

// ── トリガー登録 ──────────────────────────────────────────────────────────

/**
 * 月初1日 AM9:00 に自動実行するトリガーを登録する（冪等）
 */
function setupIndeedCostTrigger() {
  ScriptApp.getProjectTriggers().forEach(function(t) {
    if (t.getHandlerFunction() === 'fetchIndeedMonthlyCost') {
      ScriptApp.deleteTrigger(t);
    }
  });
  ScriptApp.newTrigger('fetchIndeedMonthlyCost')
    .timeBased()
    .onMonthDay(1)
    .atHour(9)
    .create();
  console.log('月次トリガーを登録しました（毎月1日 AM9:00）');
  try { SpreadsheetApp.getUi().alert('月次トリガーを登録しました（毎月1日 AM9:00）'); } catch(e) {}
}

// ── メイン: Indeed 月次広告費取得 ────────────────────────────────────────

/**
 * 先月分の Indeed 広告費を取得して AdCost_Monthly シートに書き込む。
 * 手動実行時は当月も含めた直近2ヶ月分を取得する。
 */
function fetchIndeedMonthlyCost() {
  var props = PropertiesService.getScriptProperties();
  var clientId     = props.getProperty('INDEED_CLIENT_ID');
  var clientSecret = props.getProperty('INDEED_CLIENT_SECRET');
  var employerId   = props.getProperty('INDEED_EMPLOYER_ID');

  if (!clientId || !clientSecret || !employerId) {
    var msg = 'スクリプトプロパティが未設定です。\nINDEED_CLIENT_ID / INDEED_CLIENT_SECRET / INDEED_EMPLOYER_ID を登録してください。';
    console.error(msg);
    try { SpreadsheetApp.getUi().alert(msg); } catch(e) {}
    return;
  }

  var token = _getIndeedToken_(clientId, clientSecret);
  if (!token) { console.error('Indeed トークン取得失敗'); return; }

  var ss    = SpreadsheetApp.getActiveSpreadsheet();
  var sheet = ss.getSheetByName('AdCost_Monthly');
  if (!sheet) { console.error('AdCost_Monthly シートが見つかりません'); return; }

  // 先月と当月を対象
  var today = new Date();
  var targets = [
    new Date(today.getFullYear(), today.getMonth() - 1, 1), // 先月
    new Date(today.getFullYear(), today.getMonth(), 1),      // 当月
  ];

  targets.forEach(function(d) {
    var ym   = Utilities.formatDate(d, Session.getScriptTimeZone(), 'yyyy/MM');
    var spend = _fetchSpendForMonth_(token, employerId, d);
    if (spend === null) {
      console.warn(ym + ' の広告費取得に失敗しました');
      return;
    }
    _writeSpendToSheet_(sheet, ym, spend);
    console.info(ym + ': ¥' + spend + ' を書き込みました');
  });
}

// ── Indeed API 呼び出し ───────────────────────────────────────────────────

function _getIndeedToken_(clientId, clientSecret) {
  try {
    var resp = UrlFetchApp.fetch(INDEED_TOKEN_URL, {
      method: 'post',
      payload: {
        grant_type:    'client_credentials',
        client_id:     clientId,
        client_secret: clientSecret,
        scope:         'employer_access',
      },
      muteHttpExceptions: true,
    });
    if (resp.getResponseCode() !== 200) {
      console.error('Token error: ' + resp.getContentText());
      return null;
    }
    return JSON.parse(resp.getContentText()).access_token;
  } catch (e) {
    console.error('Token fetch exception: ' + e);
    return null;
  }
}

/**
 * 指定月の合計広告費（円）を返す。取得失敗時は null。
 * @param {string} token
 * @param {string} employerId
 * @param {Date} monthDate - 月初日
 * @returns {number|null}
 */
function _fetchSpendForMonth_(token, employerId, monthDate) {
  var tz  = Session.getScriptTimeZone();
  var startDate = Utilities.formatDate(monthDate, tz, 'yyyy-MM-dd');
  // 月末日
  var lastDay = new Date(monthDate.getFullYear(), monthDate.getMonth() + 1, 0);
  var endDate = Utilities.formatDate(lastDay, tz, 'yyyy-MM-dd');

  var url = INDEED_SPEND_URL.replace('{employerId}', employerId)
    + '?startDate=' + startDate
    + '&endDate='   + endDate;

  try {
    var resp = UrlFetchApp.fetch(url, {
      headers: { Authorization: 'Bearer ' + token },
      muteHttpExceptions: true,
    });

    var code = resp.getResponseCode();
    if (code === 404 || code === 403) {
      // エンドポイントが非対応 → ログに残して手動運用を促す
      console.warn(
        'Indeed Spend API が利用できません (HTTP ' + code + ')。\n' +
        'AdCost_Monthly の Indeed 列は手動入力してください。\n' +
        'URL: ' + url
      );
      return null;
    }
    if (code !== 200) {
      console.error('Spend API error ' + code + ': ' + resp.getContentText());
      return null;
    }

    var data = JSON.parse(resp.getContentText());

    // レスポンス構造の候補（Indeed API のバージョンにより異なる）
    // パターン1: { totalSpend: 123456 }
    if (typeof data.totalSpend === 'number') return Math.round(data.totalSpend);
    // パターン2: { spend: { amount: 123456, currency: "JPY" } }
    if (data.spend && typeof data.spend.amount === 'number') return Math.round(data.spend.amount);
    // パターン3: { data: { campaigns: [{ spend: 12345 }, ...] } }
    if (data.data && Array.isArray(data.data.campaigns)) {
      var total = data.data.campaigns.reduce(function(sum, c) { return sum + (c.spend || 0); }, 0);
      return Math.round(total);
    }

    console.warn('Spend API のレスポンス構造が未知です: ' + JSON.stringify(data).substring(0, 200));
    return null;

  } catch (e) {
    console.error('Spend API exception: ' + e);
    return null;
  }
}

// ── シートへの書き込み ────────────────────────────────────────────────────

/**
 * AdCost_Monthly の指定年月行の Indeed 列（B列）に金額を書き込む。
 * 年月が見つからない場合は行を新規追加する。
 */
function _writeSpendToSheet_(sheet, ym, amount) {
  var lastRow  = sheet.getLastRow();
  var ymValues = lastRow > 1
    ? sheet.getRange(2, 1, lastRow - 1, 1).getValues()
    : [];

  var targetRow = -1;
  for (var i = 0; i < ymValues.length; i++) {
    if (String(ymValues[i][0]) === ym) { targetRow = i + 2; break; }
  }

  if (targetRow === -1) {
    // 行がなければ末尾に追加
    targetRow = lastRow + 1;
    sheet.getRange(targetRow, 1).setValue(ym);
    sheet.getRange(targetRow, 6).setFormula('=SUM(B' + targetRow + ':E' + targetRow + ')');
    sheet.getRange(targetRow, 2, 1, 5).setNumberFormat('¥#,##0');
    sheet.getRange(targetRow, 6).setNumberFormat('¥#,##0');
  }

  sheet.getRange(targetRow, 2).setValue(amount); // B列 = Indeed広告費
}

// ── デバッグ用: 手動で特定月の費用をセット ───────────────────────────────

/**
 * スクリプトプロパティが用意できる前の暫定入力用。
 * GASエディタで直接値を編集して実行する。
 *
 * 例: setIndeedCostManually('2026/06', 98000)
 */
function setIndeedCostManually(ym, amount) {
  var ss    = SpreadsheetApp.getActiveSpreadsheet();
  var sheet = ss.getSheetByName('AdCost_Monthly');
  if (!sheet) return;
  _writeSpendToSheet_(sheet, ym || '2026/06', amount || 0);
}
