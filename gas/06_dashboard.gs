/**
 * 06_dashboard.gs
 * 媒体別 ROI ダッシュボード
 *
 * シート: ROI_Dashboard
 *
 * 構造:
 *   B1: 対象年月（例: 2026/06）← ここを変えて refreshDashboard() を実行
 *
 *   媒体別サマリー（流入経路ベース）
 *   | 媒体 | 広告費 | 成約数 | 粗利合計 | 実質粗利(*) | ROI倍率 | 成約CPA | 面談数 | 面談CPA |
 *
 *   (*) 実質粗利 = 粗利 × Candidatesシートのチャネル分担割合（自社取り分）
 *
 *   固定費行（流入経路に紐づかないコスト）
 *   | Zキャリア媒体費 | ¥150,000 | — | — | — | — | — | — | — |
 *
 * セットアップ:
 *   1. setupDashboardSheet() を実行 → ROI_Dashboard シートを作成
 *   2. 対象年月(B1)を入力して refreshDashboard() を実行
 *   3. onEdit トリガーを登録しておくと B1 変更時に自動更新（setupDashboardTrigger()）
 *
 * Indeed 面談数の取得元:
 *   応募管理スプレッドシート (INTERVIEW_SS_ID) の A列=媒体名, J列=面談ステータス
 *   スクリプトプロパティ INTERVIEW_SS_ID に SpreadsheetID を登録してください。
 *   未設定の場合は面談数列を「要手動」と表示します。
 */

// ── 定数 ─────────────────────────────────────────────────────────────────────

var DASHBOARD_SHEET_NAME = 'ROI_Dashboard';
var CANDIDATES_SHEET     = 'Candidates';
var ADCOST_SHEET         = 'AdCost_Monthly';
var CHANNELS_SHEET       = 'Channels';

// Candidates 列番号
var DC_JOINING_MONTH = 2;   // B: 入社月
var DC_GROSS         = 7;   // G: 粗利
var DC_STATUS        = 12;  // L: ステータス
var DC_CHANNEL       = 15;  // O: チャネル
var DC_ACQ_SOURCE    = 21;  // U: 流入経路

// 流入経路マスター（AdCost_Monthly の列と対応）
var MEDIA_LIST = ['Indeed', 'KANOA', 'キャリカミ', 'リファラル', 'その他'];

// AdCost_Monthly 列（B〜E）
var ADCOST_COL = {
  'Indeed':   2,
  'KANOA':    3,
  'キャリカミ': 4,
};

// ── セットアップ ──────────────────────────────────────────────────────────────

function setupDashboardSheet() {
  var ss    = SpreadsheetApp.getActiveSpreadsheet();
  var sheet = ss.getSheetByName(DASHBOARD_SHEET_NAME);
  if (!sheet) sheet = ss.insertSheet(DASHBOARD_SHEET_NAME);

  sheet.clear();
  sheet.clearFormats();

  // タイトル
  sheet.getRange('A1').setValue('対象年月');
  sheet.getRange('A1').setFontWeight('bold');
  var today = new Date();
  var defaultYm = Utilities.formatDate(today, Session.getScriptTimeZone(), 'yyyy/MM');
  sheet.getRange('B1').setValue(defaultYm);
  sheet.getRange('B1').setBackground('#fff9c4');
  sheet.getRange('B1').setNote('この年月を変更して refreshDashboard() を実行してください');

  sheet.getRange('A2').setValue('※ B1の年月を変更後、上メニュー「拡張機能 > Apps Script」から refreshDashboard() を実行');
  sheet.getRange('A2').setFontColor('#888888').setFontSize(9);

  // 列幅
  var colWidths = [100, 80, 80, 100, 100, 80, 100, 80, 100, 80];
  colWidths.forEach(function(w, i) { sheet.setColumnWidth(i + 1, w); });

  _alertDash_('ROI_Dashboard シートを作成しました。B1に対象年月を入力後、refreshDashboard() を実行してください。');
}

function setupDashboardTrigger() {
  // onEdit トリガー: B1変更時に自動更新
  ScriptApp.getProjectTriggers().forEach(function(t) {
    if (t.getHandlerFunction() === 'onDashboardEdit') ScriptApp.deleteTrigger(t);
  });
  ScriptApp.newTrigger('onDashboardEdit').forSpreadsheet(SpreadsheetApp.getActive()).onEdit().create();
  _alertDash_('onEdit トリガーを登録しました。B1を変更すると自動更新されます。');
}

function onDashboardEdit(e) {
  if (!e || !e.range) return;
  var sheet = e.range.getSheet();
  if (sheet.getName() !== DASHBOARD_SHEET_NAME) return;
  if (e.range.getA1Notation() !== 'B1') return;
  refreshDashboard();
}

// ── メイン: ダッシュボード更新 ────────────────────────────────────────────────

function refreshDashboard() {
  var ss    = SpreadsheetApp.getActiveSpreadsheet();
  var sheet = ss.getSheetByName(DASHBOARD_SHEET_NAME);
  if (!sheet) { setupDashboardSheet(); sheet = ss.getSheetByName(DASHBOARD_SHEET_NAME); }

  var b1Val = sheet.getRange('B1').getValue();
  var ym;
  if (b1Val instanceof Date) {
    // Sheetsが日付型に変換した場合（例: 2026/06 → Date）
    ym = Utilities.formatDate(b1Val, Session.getScriptTimeZone(), 'yyyy/MM');
  } else {
    ym = String(b1Val).trim();
  }
  if (!ym.match(/^\d{4}\/\d{2}$/)) {
    _alertDash_('B1の形式が正しくありません。例: 2026/06');
    return;
  }

  // データ収集
  var costMap      = _getAdCostForMonth_(ss, ym);        // 媒体 → 広告費
  var candidateMap = _getCandidateData_(ss, ym);         // 媒体 → {count, gross, channelShare}
  var interviewMap = _getInterviewCount_(ss, ym);        // 媒体 → 面談数（Indeedのみ）

  // テーブル描画
  _renderTable_(sheet, ym, costMap, candidateMap, interviewMap);

  console.info(ym + ' のダッシュボードを更新しました');
}

// ── データ取得 ────────────────────────────────────────────────────────────────

function _getAdCostForMonth_(ss, ym) {
  var sheet = ss.getSheetByName(ADCOST_SHEET);
  var map = {};
  MEDIA_LIST.forEach(function(m) { map[m] = 0; });
  map['Zキャリア媒体費'] = 0;

  if (!sheet) return map;

  var lastRow = sheet.getLastRow();
  if (lastRow < 2) return map;
  var data = sheet.getRange(2, 1, lastRow - 1, 6).getValues();

  data.forEach(function(row) {
    if (String(row[0]) !== ym) return;
    map['Indeed']     = Number(row[1]) || 0;
    map['KANOA']      = Number(row[2]) || 0;
    map['キャリカミ'] = Number(row[3]) || 0;
    map['Zキャリア媒体費'] = Number(row[4]) || 0;
  });

  return map;
}

function _getCandidateData_(ss, ym) {
  var candSheet = ss.getSheetByName(CANDIDATES_SHEET);
  var chanSheet = ss.getSheetByName(CHANNELS_SHEET);

  // チャネル → 分担割合 マップを構築
  var shareMap = {};
  if (chanSheet) {
    var chanData = chanSheet.getDataRange().getValues();
    var headers  = chanData[0];
    var shareCol = headers.indexOf('分担割合');
    for (var i = 1; i < chanData.length; i++) {
      var name  = String(chanData[i][0]);
      var share = shareCol >= 0 ? Number(chanData[i][shareCol]) : 1;
      if (isNaN(share) || share === 0) share = 1;
      shareMap[name] = share;
    }
  }

  var result = {};
  MEDIA_LIST.forEach(function(m) { result[m] = { count: 0, gross: 0, netGross: 0 }; });

  if (!candSheet || candSheet.getLastRow() < 2) return result;

  var lastRow = candSheet.getLastRow();
  var data = candSheet.getRange(2, 1, lastRow - 1, DC_ACQ_SOURCE).getValues();

  data.forEach(function(row) {
    var rowYm    = String(row[DC_JOINING_MONTH - 1]);
    var status   = String(row[DC_STATUS - 1]);
    var channel  = String(row[DC_CHANNEL - 1]);
    var acqSrc   = String(row[DC_ACQ_SOURCE - 1]);
    var gross    = Number(row[DC_GROSS - 1]) || 0;

    if (rowYm !== ym) return;
    if (status !== '有効') return; // 辞退・早期離職を除外
    if (!result[acqSrc]) return;  // マスター外の流入経路はスキップ

    var share   = shareMap[channel] !== undefined ? shareMap[channel] : 1;
    result[acqSrc].count++;
    result[acqSrc].gross    += gross;
    result[acqSrc].netGross += gross * share;
  });

  return result;
}

function _getInterviewCount_(ss, ym) {
  var map = { 'Indeed': null }; // null = 未取得

  var props  = PropertiesService.getScriptProperties();
  var ssId   = props.getProperty('INTERVIEW_SS_ID');
  if (!ssId) return map; // 未設定時はスキップ

  try {
    var intSS    = SpreadsheetApp.openById(ssId);
    var intSheet = intSS.getSheets()[0];
    var lastRow  = intSheet.getLastRow();
    if (lastRow < 2) return map;

    // A列=媒体名, J列=面談ステータス
    // 日付列が存在すれば絞り込む（なければ全件でIndeed×完了をカウント）
    var data = intSheet.getRange(2, 1, lastRow - 1, 10).getValues();
    var count = 0;
    data.forEach(function(row) {
      var media  = String(row[0]);  // A列
      var status = String(row[9]);  // J列
      if (media === 'Indeed' && status === '完了') count++;
    });
    map['Indeed'] = count;
  } catch(e) {
    console.warn('応募管理SSへのアクセス失敗: ' + e);
  }

  return map;
}

// ── テーブル描画 ──────────────────────────────────────────────────────────────

function _renderTable_(sheet, ym, costMap, candidateMap, interviewMap) {
  // 3行目以降をクリア
  var lastRow = sheet.getLastRow();
  if (lastRow >= 3) sheet.getRange(3, 1, lastRow - 2, 10).clearContent().clearFormat();

  // ── セクション1: 媒体別ROIサマリー ──
  var headers = ['媒体', '広告費', '成約数', '粗利合計', '実質粗利', 'ROI倍率', '成約CPA', '面談数', '面談CPA'];
  var headerRow = sheet.getRange(3, 1, 1, headers.length);
  headerRow.setValues([headers]);
  headerRow.setFontWeight('bold').setBackground('#3c78d8').setFontColor('#ffffff');

  var currentRow = 4;
  var totCost = 0, totCount = 0, totGross = 0, totNetGross = 0, totInterview = 0;

  MEDIA_LIST.forEach(function(media) {
    var cost      = costMap[media] || 0;
    var cand      = candidateMap[media] || { count: 0, gross: 0, netGross: 0 };
    var count     = cand.count;
    var gross     = cand.gross;
    var netGross  = cand.netGross;
    var interviews = interviewMap[media];  // null or number

    var roi       = (cost > 0 && netGross > 0) ? (netGross / cost) : null;
    var cpa       = (cost > 0 && count > 0)    ? Math.round(cost / count) : null;
    var intCpa    = (cost > 0 && interviews > 0) ? Math.round(cost / interviews) : null;

    var roiStr    = roi       !== null ? roi.toFixed(1) + 'x'  : '—';
    var cpaStr    = cpa       !== null ? '¥' + _fmt_(cpa)      : '—';
    var intStr    = interviews !== null ? interviews             : '要設定';
    var intCpaStr = intCpa    !== null ? '¥' + _fmt_(intCpa)   : (media === 'Indeed' ? '—' : '');

    var row = [
      media,
      cost     > 0 ? cost     : '—',
      count    > 0 ? count    : '—',
      gross    > 0 ? gross    : '—',
      netGross > 0 ? netGross : '—',
      roiStr,
      cpaStr,
      media === 'Indeed' ? intStr    : '',
      media === 'Indeed' ? intCpaStr : '',
    ];

    sheet.getRange(currentRow, 1, 1, row.length).setValues([row]);

    // 色分け
    var bg = (currentRow % 2 === 0) ? '#f8f9fa' : '#ffffff';
    sheet.getRange(currentRow, 1, 1, row.length).setBackground(bg);

    // ROI倍率を色で強調
    if (roi !== null) {
      var roiCell = sheet.getRange(currentRow, 6);
      if (roi >= 3)      roiCell.setBackground('#b7e1cd').setFontWeight('bold'); // 緑: 優良
      else if (roi >= 1) roiCell.setBackground('#fff3cd');                        // 黄: 損益分岐以上
      else               roiCell.setBackground('#f4cccc');                        // 赤: 赤字
    }

    // 通貨書式
    if (cost > 0)     sheet.getRange(currentRow, 2).setNumberFormat('¥#,##0');
    if (gross > 0)    sheet.getRange(currentRow, 4).setNumberFormat('¥#,##0');
    if (netGross > 0) sheet.getRange(currentRow, 5).setNumberFormat('¥#,##0');

    totCost      += cost;
    totCount     += count;
    totGross     += gross;
    totNetGross  += netGross;
    if (typeof interviews === 'number') totInterview += interviews;

    currentRow++;
  });

  // 合計行
  var totRoi    = (totCost > 0 && totNetGross > 0) ? (totNetGross / totCost).toFixed(1) + 'x' : '—';
  var totCpa    = (totCost > 0 && totCount > 0)    ? '¥' + _fmt_(Math.round(totCost / totCount)) : '—';
  var totIntCpa = (totCost > 0 && totInterview > 0) ? '¥' + _fmt_(Math.round(totCost / totInterview)) : '—';

  var totRow = ['合計', totCost, totCount, totGross, totNetGross, totRoi, totCpa, totInterview || '—', totIntCpa];
  var totRange = sheet.getRange(currentRow, 1, 1, totRow.length);
  totRange.setValues([totRow]);
  totRange.setFontWeight('bold').setBackground('#e8f0fe');
  sheet.getRange(currentRow, 2).setNumberFormat('¥#,##0');
  sheet.getRange(currentRow, 4).setNumberFormat('¥#,##0');
  sheet.getRange(currentRow, 5).setNumberFormat('¥#,##0');

  currentRow += 2;

  // ── セクション2: 固定費（参考） ──
  sheet.getRange(currentRow, 1).setValue('【固定費（参考）】').setFontWeight('bold');
  currentRow++;

  var fixedHeaders = ['項目', '月額', '備考'];
  sheet.getRange(currentRow, 1, 1, 3).setValues([fixedHeaders]).setFontWeight('bold').setBackground('#eeeeee');
  currentRow++;

  var zCost = costMap['Zキャリア媒体費'] || 0;
  sheet.getRange(currentRow, 1, 1, 3).setValues([['Zキャリア媒体費', zCost, 'プラットフォーム月額（流入経路とは別管理）']]);
  if (zCost > 0) sheet.getRange(currentRow, 2).setNumberFormat('¥#,##0');

  currentRow += 2;

  // ── セクション3: 注記 ──
  var notes = [
    '■ 実質粗利 = 粗利 × チャネル分担割合（自社取り分）',
    '■ ROI倍率 = 実質粗利 ÷ 広告費（1.0x = 損益分岐）',
    '■ 成約CPA = 広告費 ÷ 成約数',
    '■ 面談CPA = Indeed広告費 ÷ 面談実施数（Indeedのみ）',
    '■ 面談数は応募管理SSのJ列「完了」件数を参照（INTERVIEW_SS_IDを設定した場合）',
    '■ ステータス「有効」の成約のみ集計（辞退・早期離職は除外）',
    '■ Zキャリア媒体費はROI計算の分母に含まない（固定オーバーヘッドとして別掲）',
  ];
  notes.forEach(function(note) {
    sheet.getRange(currentRow, 1).setValue(note).setFontColor('#555555').setFontSize(9);
    currentRow++;
  });

  // タイトル行を更新
  sheet.getRange('C1').setValue('最終更新: ' + Utilities.formatDate(new Date(), Session.getScriptTimeZone(), 'yyyy/MM/dd HH:mm'));
  sheet.getRange('C1').setFontColor('#888888').setFontSize(9);
}

// ── ユーティリティ ────────────────────────────────────────────────────────────

function _fmt_(n) {
  return n.toString().replace(/\B(?=(\d{3})+(?!\d))/g, ',');
}

function _alertDash_(msg) {
  console.log(msg);
  try { SpreadsheetApp.getUi().alert(msg); } catch(e) {}
}
