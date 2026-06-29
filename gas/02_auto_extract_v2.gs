/**
 * 02_auto_extract_v2.gs
 * Slack成約報告の自動取込 (v5対応: 流入経路フィールド追加)
 *
 * このファイルで 02_auto_extract.gs を上書き置き換えてください。
 *
 * Slackフォーマット（新）:
 *   【成約報告】
 *   入社日：2026年5月1日
 *   候補者: 松本偲希
 *   CA: 松本歩太
 *   企業: 株式会社エール
 *   売上（粗利）：1000000（500000）
 *   業種（職種）:建設業（施工管理）
 *   流入経路：Indeed        ← 新規追加
 *   チャネル：ゼロタレ
 */

// ── カラム定数 ────────────────────────────────────────────────────────────

var COL_JOINING_DATE     = 1;   // A: 入社日
var COL_JOINING_MONTH    = 2;   // B: 入社月
var COL_NAME             = 3;   // C: 候補者氏名
var COL_CA               = 4;   // D: CA
var COL_COMPANY          = 5;   // E: 企業
var COL_SALES            = 6;   // F: 売上(円)
var COL_GROSS            = 7;   // G: 粗利(円)
var COL_INDUSTRY         = 8;   // H: 業種
var COL_JOB_TYPE         = 9;   // I: 職種
var COL_DATA_SOURCE      = 10;  // J: データソース
var COL_IMPORTED_AT      = 11;  // K: 取込日時
var COL_STATUS           = 12;  // L: ステータス
var COL_DECLINED_DATE    = 13;  // M: 辞退日
var COL_SLACK_TS         = 14;  // N: Slack_TS
var COL_CHANNEL          = 15;  // O: チャネル
var COL_EARLY_LEAVE_DATE = 16;  // P: 早期離職日
var COL_REFUND           = 17;  // Q: 返金額
var COL_START_MONTH      = 18;  // R: 稼働開始月
var COL_PLANNED_MONTHS   = 19;  // S: 予定稼働月数
var COL_ACTUAL_MONTHS    = 20;  // T: 実稼働月数
var COL_ACQ_SOURCE       = 21;  // U: 流入経路 ← v5追加

// ── トリガー登録 ─────────────────────────────────────────────────────────

function setupDailyTrigger() {
  // 既存トリガーを削除してから再登録（冪等）
  ScriptApp.getProjectTriggers().forEach(function(t) {
    if (t.getHandlerFunction() === 'dailyExtract') {
      ScriptApp.deleteTrigger(t);
    }
  });
  ScriptApp.newTrigger('dailyExtract')
    .timeBased()
    .everyDays(1)
    .atHour(8)
    .create();
}

// ── メイン: 日次取込 ──────────────────────────────────────────────────────

function dailyExtract() {
  var props = PropertiesService.getScriptProperties();
  var token = props.getProperty('SLACK_BOT_TOKEN');
  var channelId = props.getProperty('SLACK_CHANNEL_ID');
  if (!token || !channelId) {
    console.error('SLACK_BOT_TOKEN または SLACK_CHANNEL_ID が未設定');
    return;
  }

  var ss = SpreadsheetApp.getActiveSpreadsheet();
  var sheet = ss.getSheetByName('Candidates');
  if (!sheet) throw new Error('Candidatesシートが見つかりません');

  // 取込済みのSlack_TSを収集
  var imported = _getImportedTs_(sheet);

  // Slack APIからメッセージ取得（過去7日）
  var oldest = (Date.now() / 1000 - 7 * 86400).toString();
  var url = 'https://slack.com/api/conversations.history'
    + '?channel=' + channelId
    + '&oldest=' + oldest
    + '&limit=200';
  var res = UrlFetchApp.fetch(url, {
    headers: { Authorization: 'Bearer ' + token },
    muteHttpExceptions: true,
  });
  var json = JSON.parse(res.getContentText());
  if (!json.ok) {
    console.error('Slack API error: ' + json.error);
    return;
  }

  var messages = json.messages || [];
  messages.forEach(function(msg) {
    var text = msg.text || '';
    if (text.indexOf('【成約報告】') === -1) return;
    if (imported[msg.ts]) return; // 取込済みスキップ

    var parsed = parseSlackDealMessage_(text);
    if (!parsed) return;
    parsed.slackTs = msg.ts;

    appendCandidate_(sheet, parsed);
  });
}

// ── パーサー ─────────────────────────────────────────────────────────────

/**
 * Slackメッセージを解析してオブジェクトを返す
 * @param {string} text
 * @returns {Object|null}
 */
function parseSlackDealMessage_(text) {
  if (text.indexOf('【成約報告】') === -1) return null;

  var result = {};

  // 入社日
  var dateMatch = text.match(/入社日[：:]\s*(\d{4})年(\d{1,2})月(\d{1,2})日/);
  if (dateMatch) {
    result.joiningDate = new Date(
      parseInt(dateMatch[1]),
      parseInt(dateMatch[2]) - 1,
      parseInt(dateMatch[3])
    );
  }

  // 候補者
  var nameMatch = text.match(/候補者[：:]\s*(.+)/);
  result.candidateName = nameMatch ? nameMatch[1].trim() : '';

  // CA
  var caMatch = text.match(/CA[：:]\s*(.+)/);
  result.ca = caMatch ? caMatch[1].trim() : '';

  // 企業
  var companyMatch = text.match(/企業[：:]\s*(.+)/);
  result.company = companyMatch ? companyMatch[1].trim() : '';

  // 売上（粗利）: 1000000（500000）
  var salesMatch = text.match(/売上[（(]粗利[）)][：:]\s*([\d,]+)[（(]([\d,]+)[）)]/);
  if (salesMatch) {
    result.sales = parseInt(salesMatch[1].replace(/,/g, ''), 10);
    result.gross = parseInt(salesMatch[2].replace(/,/g, ''), 10);
  }

  // 業種（職種）
  var indMatch = text.match(/業種[（(]職種[）)][：:]\s*(.+?)[（(](.+?)[）)]/);
  if (indMatch) {
    result.industry = indMatch[1].trim();
    result.jobType = indMatch[2].trim();
  }

  // 流入経路（新規）
  var srcMatch = text.match(/流入経路[：:]\s*(.+)/);
  result.acquisitionSource = srcMatch ? srcMatch[1].trim() : '';

  // チャネル
  var chMatch = text.match(/チャネル[：:]\s*(.+)/);
  result.channel = chMatch ? chMatch[1].trim() : '';

  return result;
}

// ── 書き込み ──────────────────────────────────────────────────────────────

/**
 * Candidatesシートに1行追記する
 * @param {GoogleAppsScript.Spreadsheet.Sheet} sheet
 * @param {Object} data parseSlackDealMessage_ の返り値 + slackTs
 */
function appendCandidate_(sheet, data) {
  var row = sheet.getLastRow() + 1;
  var now = new Date();

  var joiningDate = data.joiningDate || '';
  var joiningMonth = joiningDate
    ? Utilities.formatDate(joiningDate, Session.getScriptTimeZone(), 'yyyy/MM')
    : '';

  sheet.getRange(row, COL_JOINING_DATE).setValue(joiningDate);
  sheet.getRange(row, COL_JOINING_MONTH).setValue(joiningMonth);
  sheet.getRange(row, COL_NAME).setValue(data.candidateName || '');
  sheet.getRange(row, COL_CA).setValue(data.ca || '');
  sheet.getRange(row, COL_COMPANY).setValue(data.company || '');
  sheet.getRange(row, COL_SALES).setValue(data.sales || '');
  sheet.getRange(row, COL_GROSS).setValue(data.gross || '');
  sheet.getRange(row, COL_INDUSTRY).setValue(data.industry || '');
  sheet.getRange(row, COL_JOB_TYPE).setValue(data.jobType || '');
  sheet.getRange(row, COL_DATA_SOURCE).setValue('Slack');
  sheet.getRange(row, COL_IMPORTED_AT).setValue(now);
  sheet.getRange(row, COL_STATUS).setValue('有効');
  sheet.getRange(row, COL_SLACK_TS).setValue(data.slackTs || '');
  sheet.getRange(row, COL_CHANNEL).setValue(data.channel || '');
  sheet.getRange(row, COL_ACQ_SOURCE).setValue(data.acquisitionSource || '');
}

// ── ヘルパー ─────────────────────────────────────────────────────────────

function _getImportedTs_(sheet) {
  var lastRow = sheet.getLastRow();
  if (lastRow < 2) return {};
  var tsValues = sheet.getRange(2, COL_SLACK_TS, lastRow - 1, 1).getValues();
  var map = {};
  tsValues.forEach(function(row) {
    if (row[0]) map[String(row[0])] = true;
  });
  return map;
}
