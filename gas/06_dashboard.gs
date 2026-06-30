/**
 * 06_dashboard.gs
 * 媒体別 ROI ダッシュボード
 *
 * B1 に対象期間を入力して refreshDashboard() を実行するだけで更新される。
 *
 *   B1 = "全期間"   → Candidates の全データを流入経路別に集計
 *   B1 = "2026/06"  → 入社月が 2026/06 のデータのみ集計
 *
 * セットアップ:
 *   1. setupDashboardSheet() を実行（初回のみ）
 *   2. B1 を入力して refreshDashboard() を実行
 *   3. setupDashboardTrigger() を実行すると B1 変更時に自動更新
 */

// ── 定数 ─────────────────────────────────────────────────────────────────────

var DASHBOARD_SHEET_NAME = 'ROI_Dashboard';
var CANDIDATES_SHEET     = 'Candidates';
var ADCOST_SHEET         = 'AdCost_Monthly';
var CHANNELS_SHEET       = 'Channels';

// Candidates 列番号（1始まり）
var DC_JOINING_MONTH = 2;   // B: 入社月
var DC_GROSS         = 7;   // G: 粗利
var DC_STATUS        = 12;  // L: ステータス
var DC_CHANNEL       = 15;  // O: チャネル
var DC_ACQ_SOURCE    = 21;  // U: 流入経路（migrateV5 で追加）

// 流入経路マスター
var MEDIA_LIST = ['Indeed', 'KANOA', 'キャリカミ', 'リファラル', 'その他'];

// ── セットアップ ──────────────────────────────────────────────────────────────

function setupDashboardSheet() {
  var ss    = SpreadsheetApp.getActiveSpreadsheet();
  var sheet = ss.getSheetByName(DASHBOARD_SHEET_NAME);
  if (!sheet) sheet = ss.insertSheet(DASHBOARD_SHEET_NAME);

  sheet.clear();
  sheet.clearFormats();

  sheet.getRange('A1').setValue('対象期間').setFontWeight('bold');
  sheet.getRange('B1').setValue('全期間').setBackground('#fff9c4');
  sheet.getRange('B1').setNote('「全期間」または「2026/06」のように入力して refreshDashboard() を実行');
  sheet.getRange('A2').setValue('※ B1を変更後、GASエディタで refreshDashboard() を実行')
    .setFontColor('#888888').setFontSize(9);

  var colWidths = [110, 90, 70, 110, 110, 80, 100, 70, 100];
  colWidths.forEach(function(w, i) { sheet.setColumnWidth(i + 1, w); });

  _alertDash_('ROI_Dashboard を作成しました。refreshDashboard() を実行してください。');
}

function setupDashboardTrigger() {
  ScriptApp.getProjectTriggers().forEach(function(t) {
    if (t.getHandlerFunction() === 'onDashboardEdit') ScriptApp.deleteTrigger(t);
  });
  ScriptApp.newTrigger('onDashboardEdit')
    .forSpreadsheet(SpreadsheetApp.getActive()).onEdit().create();
  _alertDash_('onEdit トリガーを登録しました。B1変更時に自動更新されます。');
}

function onDashboardEdit(e) {
  if (!e || !e.range) return;
  if (e.range.getSheet().getName() !== DASHBOARD_SHEET_NAME) return;
  if (e.range.getA1Notation() !== 'B1') return;
  refreshDashboard();
}

// ── メイン ────────────────────────────────────────────────────────────────────

/**
 * Candidates シートの流入経路列を集計し、ROI_Dashboard を更新する。
 * B1 = "全期間" → 全データ集計
 * B1 = "yyyy/MM" → その月の入社者のみ集計
 */
function refreshDashboard() {
  var ss    = SpreadsheetApp.getActiveSpreadsheet();
  var sheet = ss.getSheetByName(DASHBOARD_SHEET_NAME);
  if (!sheet) { setupDashboardSheet(); sheet = ss.getSheetByName(DASHBOARD_SHEET_NAME); }

  // B1 から対象期間を読む（日付型・文字列どちらでも対応）
  var b1Val = sheet.getRange('B1').getValue();
  var period; // "全期間" or "yyyy/MM"
  if (b1Val instanceof Date) {
    period = Utilities.formatDate(b1Val, Session.getScriptTimeZone(), 'yyyy/MM');
  } else {
    period = String(b1Val).trim();
  }
  if (!period) period = '全期間';

  // ── Candidates から流入経路別に集計 ──
  var candidateMap = _aggregateCandidates_(ss, period);

  // ── AdCost_Monthly から媒体別コストを集計 ──
  var costMap = _aggregateCosts_(ss, period);

  // ── 面談数（Indeed のみ、INTERVIEW_SS_ID 設定時） ──
  var interviewMap = _getInterviewCount_(ss, period);

  // ── チャネル分担割合マップ ──
  var shareMap = _buildShareMap_(ss);

  // ── 描画 ──
  _renderTable_(ss, sheet, period, costMap, candidateMap, interviewMap, shareMap);

  console.info('ROI_Dashboard 更新完了（期間: ' + period + '）');
}

// ── データ集計 ────────────────────────────────────────────────────────────────

/**
 * 【デバッグ用】Candidates の読み取り状況をログに出力する。
 * GASエディタで実行して「実行数」タブでログを確認する。
 */
function debugCandidates() {
  var ss    = SpreadsheetApp.getActiveSpreadsheet();
  var sheet = ss.getSheetByName(CANDIDATES_SHEET);
  if (!sheet) { console.log('Candidatesシートが見つかりません'); return; }

  var lastRow = sheet.getLastRow();
  var lastCol = sheet.getLastColumn();
  console.log('Candidates: ' + (lastRow - 1) + '行, ' + lastCol + '列');
  console.log('U列(流入経路)は列番号 ' + DC_ACQ_SOURCE + ' = ' + (lastCol >= DC_ACQ_SOURCE ? '存在する' : '存在しない（migrateV5未実行）'));

  if (lastRow < 2) { console.log('データなし'); return; }

  var readCol = Math.max(lastCol, DC_ACQ_SOURCE);
  var data = sheet.getRange(2, 1, Math.min(lastRow - 1, 10), readCol).getValues(); // 先頭10行

  data.forEach(function(row, i) {
    var joinYm  = _toYm_(row[DC_JOINING_MONTH - 1]);
    var status  = String(row[DC_STATUS - 1]  || '(空)');
    var channel = String(row[DC_CHANNEL - 1] || '(空)');
    var acqSrc  = readCol >= DC_ACQ_SOURCE ? String(row[DC_ACQ_SOURCE - 1] || '(空)') : '(列なし)';
    var gross   = row[DC_GROSS - 1];
    console.log('行' + (i + 2) + ': 入社月=' + joinYm + ' ステータス=' + status + ' 流入経路=' + acqSrc + ' チャネル=' + channel + ' 粗利=' + gross);
  });
}

/**
 * Candidates シートを流入経路でグループ化して集計する。
 * period = "全期間" のときは月フィルターなし。
 *
 * @returns {{ [media]: { count, gross } }}
 */
function _aggregateCandidates_(ss, period) {
  var result = {};
  MEDIA_LIST.forEach(function(m) { result[m] = { count: 0, gross: 0 }; });

  var sheet = ss.getSheetByName(CANDIDATES_SHEET);
  if (!sheet || sheet.getLastRow() < 2) return result;

  var lastRow = sheet.getLastRow();
  var lastCol = Math.max(sheet.getLastColumn(), DC_ACQ_SOURCE);
  var data    = sheet.getRange(2, 1, lastRow - 1, lastCol).getValues();

  data.forEach(function(row) {
    var status  = String(row[DC_STATUS - 1] || '');
    var acqSrc  = String(row[DC_ACQ_SOURCE - 1] || '').trim();
    var gross   = Number(row[DC_GROSS - 1]) || 0;
    var joinYm  = _toYm_(row[DC_JOINING_MONTH - 1]);

    // 明示的に除外するステータスのみスキップ（辞退・早期離職・返金）
    if (status === '辞退' || status === '早期離職' || status === '返金') return;

    // 月フィルター
    if (period !== '全期間' && joinYm !== period) return;

    // 流入経路が空またはマスター外は「その他」に分類
    if (!acqSrc || !result[acqSrc]) acqSrc = 'その他';

    result[acqSrc].count++;
    result[acqSrc].gross += gross;
  });

  return result;
}

/**
 * AdCost_Monthly から媒体別コストを集計する。
 * period = "全期間" のときは全月合計。
 *
 * @returns {{ Indeed, KANOA, キャリカミ, Zキャリア媒体費 }}
 */
function _aggregateCosts_(ss, period) {
  var map = { 'Indeed': 0, 'KANOA': 0, 'キャリカミ': 0, 'Zキャリア媒体費': 0 };

  var sheet = ss.getSheetByName(ADCOST_SHEET);
  if (!sheet || sheet.getLastRow() < 2) return map;

  var lastRow = sheet.getLastRow();
  var data    = sheet.getRange(2, 1, lastRow - 1, 6).getValues();

  data.forEach(function(row) {
    var rowYm = _toYm_(row[0]);
    if (period !== '全期間' && rowYm !== period) return;

    map['Indeed']          += Number(row[1]) || 0;
    map['KANOA']           += Number(row[2]) || 0;
    map['キャリカミ']      += Number(row[3]) || 0;
    map['Zキャリア媒体費'] += Number(row[4]) || 0;
  });

  return map;
}

/**
 * Channels シートからチャネル名 → 分担割合（自社取り分）のマップを返す。
 * 分担割合未設定のチャネルは 1（100%）とみなす。
 */
function _buildShareMap_(ss) {
  var map = {};
  var sheet = ss.getSheetByName(CHANNELS_SHEET);
  if (!sheet) return map;

  var data     = sheet.getDataRange().getValues();
  var headers  = data[0];
  var shareCol = headers.indexOf('分担割合');

  for (var i = 1; i < data.length; i++) {
    var name  = String(data[i][0] || '').trim();
    if (!name) continue;
    var share = shareCol >= 0 ? Number(data[i][shareCol]) : NaN;
    map[name] = (!isNaN(share) && share > 0) ? share : 1;
  }
  return map;
}

/**
 * 応募管理スプレッドシートから Indeed の面談完了数を取得する。
 * INTERVIEW_SS_ID スクリプトプロパティが未設定の場合は null を返す。
 */
function _getInterviewCount_(ss, period) {
  var map = { 'Indeed': null };

  var ssId = PropertiesService.getScriptProperties().getProperty('INTERVIEW_SS_ID');
  if (!ssId) return map;

  try {
    var intSheet = SpreadsheetApp.openById(ssId).getSheets()[0];
    var lastRow  = intSheet.getLastRow();
    if (lastRow < 2) return map;

    // A列=媒体名, J列=面談ステータス
    var data  = intSheet.getRange(2, 1, lastRow - 1, 10).getValues();
    var count = 0;
    data.forEach(function(row) {
      if (String(row[0]) === 'Indeed' && String(row[9]) === '完了') count++;
    });
    map['Indeed'] = count;
  } catch(e) {
    console.warn('応募管理SS アクセス失敗: ' + e);
  }

  return map;
}

// ── 描画 ─────────────────────────────────────────────────────────────────────

function _renderTable_(ss, sheet, period, costMap, candidateMap, interviewMap, shareMap) {
  // 3行目以降をクリア
  var lastRow = sheet.getLastRow();
  if (lastRow >= 3) sheet.getRange(3, 1, lastRow - 2, 10).clearContent().clearFormat();

  // ヘッダー
  var headers = ['媒体', '広告費', '成約数', '粗利合計', '実質粗利', 'ROI倍率', '成約CPA', '面談数', '面談CPA'];
  var hRange = sheet.getRange(3, 1, 1, headers.length);
  hRange.setValues([headers]).setFontWeight('bold').setBackground('#3c78d8').setFontColor('#ffffff');

  var curRow = 4;
  var tot = { cost: 0, count: 0, gross: 0, netGross: 0, interviews: 0 };

  MEDIA_LIST.forEach(function(media) {
    var cost      = costMap[media] || 0;
    var cand      = candidateMap[media] || { count: 0, gross: 0 };
    var count     = cand.count;
    var gross     = cand.gross;
    var interviews = interviewMap[media]; // null or number

    // 実質粗利: 成約ごとにチャネル分担割合を掛けるのが理想だが、
    // ここでは簡略化として Candidates から直接集計した粗利をそのまま使い
    // shareMap は "チャネルが未設定＝自社100%" としてそのまま粗利を採用
    // （チャネルを考慮した実質粗利は _aggregateCandidatesWithShare_ で対応可能）
    var netGross = _calcNetGross_(ss, media, period, shareMap);

    var roi    = (cost > 0 && netGross > 0) ? netGross / cost           : null;
    var cpa    = (cost > 0 && count > 0)    ? Math.round(cost / count)  : null;
    var intCpa = (cost > 0 && interviews > 0) ? Math.round(cost / interviews) : null;

    var row = [
      media,
      cost     > 0 ? cost     : '—',
      count    > 0 ? count    : '—',
      gross    > 0 ? gross    : '—',
      netGross > 0 ? netGross : '—',
      roi    !== null ? roi.toFixed(1) + 'x'  : '—',
      cpa    !== null ? '¥' + _fmt_(cpa)      : '—',
      media === 'Indeed' ? (interviews !== null ? interviews : '要設定') : '',
      media === 'Indeed' ? (intCpa !== null ? '¥' + _fmt_(intCpa) : '—') : '',
    ];

    sheet.getRange(curRow, 1, 1, row.length).setValues([row]);
    sheet.getRange(curRow, 1, 1, row.length).setBackground(curRow % 2 === 0 ? '#f8f9fa' : '#ffffff');

    // ROI 色分け
    if (roi !== null) {
      var roiCell = sheet.getRange(curRow, 6);
      if      (roi >= 3) roiCell.setBackground('#b7e1cd').setFontWeight('bold');
      else if (roi >= 1) roiCell.setBackground('#fff3cd');
      else               roiCell.setBackground('#f4cccc');
    }

    // 通貨書式
    if (cost > 0)     sheet.getRange(curRow, 2).setNumberFormat('¥#,##0');
    if (gross > 0)    sheet.getRange(curRow, 4).setNumberFormat('¥#,##0');
    if (netGross > 0) sheet.getRange(curRow, 5).setNumberFormat('¥#,##0');

    tot.cost      += cost;
    tot.count     += count;
    tot.gross     += gross;
    tot.netGross  += netGross;
    if (typeof interviews === 'number') tot.interviews += interviews;

    curRow++;
  });

  // 合計行
  var totRoi    = (tot.cost > 0 && tot.netGross > 0) ? (tot.netGross / tot.cost).toFixed(1) + 'x' : '—';
  var totCpa    = (tot.cost > 0 && tot.count > 0)    ? '¥' + _fmt_(Math.round(tot.cost / tot.count)) : '—';
  var totIntCpa = (tot.cost > 0 && tot.interviews > 0) ? '¥' + _fmt_(Math.round(tot.cost / tot.interviews)) : '—';

  var totRow = ['合計', tot.cost, tot.count, tot.gross, tot.netGross, totRoi, totCpa, tot.interviews || '—', totIntCpa];
  var totRange = sheet.getRange(curRow, 1, 1, totRow.length);
  totRange.setValues([totRow]).setFontWeight('bold').setBackground('#e8f0fe');
  [2, 4, 5].forEach(function(c) { sheet.getRange(curRow, c).setNumberFormat('¥#,##0'); });

  curRow += 2;

  // 固定費セクション
  sheet.getRange(curRow, 1).setValue('【固定費（参考）】').setFontWeight('bold');
  curRow++;
  sheet.getRange(curRow, 1, 1, 3).setValues([['項目', '月額（累計）', '備考']]).setFontWeight('bold').setBackground('#eeeeee');
  curRow++;
  var zCost = costMap['Zキャリア媒体費'] || 0;
  sheet.getRange(curRow, 1, 1, 3).setValues([['Zキャリア媒体費', zCost > 0 ? zCost : '—', 'プラットフォーム月額（流入経路に紐づかないコスト）']]);
  if (zCost > 0) sheet.getRange(curRow, 2).setNumberFormat('¥#,##0');

  curRow += 2;

  // 注記
  [
    '■ 実質粗利 = 粗利 × チャネル分担割合（Channels シートの「自社取り分」）',
    '■ ROI倍率 = 実質粗利 ÷ 広告費（1.0x = 損益分岐）',
    '■ 成約CPA = 広告費 ÷ 成約数',
    '■ 面談CPA = Indeed広告費 ÷ 面談実施数（Indeedのみ）',
    '■ Candidates ステータス「有効」（または空欄）の成約のみ集計',
    '■ Zキャリア媒体費は ROI 計算の分母に含まない（固定費として別掲）',
  ].forEach(function(note) {
    sheet.getRange(curRow, 1).setValue(note).setFontColor('#555555').setFontSize(9);
    curRow++;
  });

  // 更新日時
  sheet.getRange('C1').setValue('最終更新: ' + Utilities.formatDate(new Date(), Session.getScriptTimeZone(), 'yyyy/MM/dd HH:mm'))
    .setFontColor('#888888').setFontSize(9);
}

/**
 * 実質粗利を計算する（チャネル分担割合を反映）。
 * Candidates の各行: 粗利 × そのチャネルの分担割合 を媒体別に合計。
 */
function _calcNetGross_(ss, targetMedia, period, shareMap) {
  var sheet = ss.getSheetByName(CANDIDATES_SHEET);
  if (!sheet || sheet.getLastRow() < 2) return 0;

  var lastRow = sheet.getLastRow();
  var lastCol = Math.max(sheet.getLastColumn(), DC_ACQ_SOURCE);
  var data    = sheet.getRange(2, 1, lastRow - 1, lastCol).getValues();
  var total   = 0;

  data.forEach(function(row) {
    var status  = String(row[DC_STATUS - 1] || '');
    var acqSrc  = String(row[DC_ACQ_SOURCE - 1] || '').trim();
    var channel = String(row[DC_CHANNEL - 1] || '').trim();
    var gross   = Number(row[DC_GROSS - 1]) || 0;
    var joinYm  = _toYm_(row[DC_JOINING_MONTH - 1]);

    if (status === '辞退' || status === '早期離職' || status === '返金') return;
    // 流入経路が空またはマスター外は「その他」として扱う
    if (!acqSrc) acqSrc = 'その他';
    if (acqSrc !== targetMedia) return;
    if (period !== '全期間' && joinYm !== period) return;

    var share = shareMap[channel] !== undefined ? shareMap[channel] : 1;
    total += gross * share;
  });

  return Math.round(total);
}

// ── ユーティリティ ────────────────────────────────────────────────────────────

function _toYm_(val) {
  if (val instanceof Date) {
    return Utilities.formatDate(val, Session.getScriptTimeZone(), 'yyyy/MM');
  }
  var s = String(val).trim();
  if (s.match(/^\d{4}\/\d{2}\/\d{2}$/)) return s.substring(0, 7);
  // "yyyy-MM" or "yyyy-MM-dd" (TEXT関数のyyyy-mm形式) → "yyyy/MM" に正規化
  if (s.match(/^\d{4}-\d{2}/)) return s.substring(0, 7).replace('-', '/');
  return s;
}

function _fmt_(n) {
  return n.toString().replace(/\B(?=(\d{3})+(?!\d))/g, ',');
}

function _alertDash_(msg) {
  console.log(msg);
  try { SpreadsheetApp.getUi().alert(msg); } catch(e) {}
}
