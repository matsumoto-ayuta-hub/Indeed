/**
 * Migration v6: AdCost_Monthly シート作成
 *
 * 構造: 行=年月、列=媒体
 *
 *   年月 | Indeed広告費 | KANOA費 | キャリカミ費 | Zキャリア媒体費 | 合計
 *
 * - Indeed: 05_adcost_indeed.gs の fetchIndeedMonthlyCost() で自動入力
 * - KANOA / キャリカミ / Zキャリア媒体費: 手動入力
 * - 合計: SUM数式で自動計算
 *
 * 実行方法: GASエディタで migrateV6 を選択して「実行」
 */

var MIGRATION_V6_KEY   = 'schema_version';
var MIGRATION_V6_VALUE = 6;

// 月を何ヶ月分初期生成するか（過去6ヶ月 + 当月 + 先6ヶ月）
var ADCOST_INIT_MONTHS = 13;

function migrateV6() {
  var ss = SpreadsheetApp.getActiveSpreadsheet();
  var props = PropertiesService.getScriptProperties();
  var current = parseInt(props.getProperty(MIGRATION_V6_KEY) || '0', 10);

  if (current >= MIGRATION_V6_VALUE) {
    SpreadsheetApp.getUi().alert('v6マイグレーション済みです（スキップ）');
    return;
  }

  _createAdCostMonthlySheet_(ss);

  props.setProperty(MIGRATION_V6_KEY, String(MIGRATION_V6_VALUE));
  SpreadsheetApp.getUi().alert('v6マイグレーション完了: AdCost_Monthly シートを作成しました');
}

// ── AdCost_Monthly シート作成 ────────────────────────────────────────────────

function _createAdCostMonthlySheet_(ss) {
  if (ss.getSheetByName('AdCost_Monthly')) return; // 冪等

  var sheet = ss.insertSheet('AdCost_Monthly');

  // ── ヘッダー行 ──
  var headers = [
    '年月',
    'Indeed広告費',
    'KANOA費',
    'キャリカミ費',
    'Zキャリア媒体費',
    '合計',
  ];
  var headerRange = sheet.getRange(1, 1, 1, headers.length);
  headerRange.setValues([headers]);
  headerRange.setFontWeight('bold');
  headerRange.setBackground('#e8f0fe');
  sheet.setFrozenRows(1);

  // ── 列幅 ──
  sheet.setColumnWidth(1, 80);   // 年月
  sheet.setColumnWidth(2, 110);  // Indeed
  sheet.setColumnWidth(3, 90);   // KANOA
  sheet.setColumnWidth(4, 100);  // キャリカミ
  sheet.setColumnWidth(5, 120);  // Zキャリア媒体費
  sheet.setColumnWidth(6, 80);   // 合計

  // ── 月行の初期生成 ──
  var today = new Date();
  // 過去6ヶ月から始める
  var startDate = new Date(today.getFullYear(), today.getMonth() - 6, 1);

  for (var i = 0; i < ADCOST_INIT_MONTHS; i++) {
    var d = new Date(startDate.getFullYear(), startDate.getMonth() + i, 1);
    var ym = Utilities.formatDate(d, Session.getScriptTimeZone(), 'yyyy/MM');
    var row = i + 2; // 2行目から

    sheet.getRange(row, 1).setValue(ym);

    // Indeed: 自動入力されるまで空欄（数値のみ）
    // KANOA: ¥27,500 固定（手動確認後に編集可）
    sheet.getRange(row, 3).setValue(27500);

    // キャリカミ: 2026/07から ¥36,300
    var isAfterJuly2026 = (d.getFullYear() > 2026) || (d.getFullYear() === 2026 && d.getMonth() >= 6);
    if (isAfterJuly2026) {
      sheet.getRange(row, 4).setValue(36300);
    }

    // Zキャリア媒体費: ¥150,000 固定
    sheet.getRange(row, 5).setValue(150000);

    // 合計: SUM数式（B〜E列）
    var sumFormula = '=SUM(B' + row + ':E' + row + ')';
    sheet.getRange(row, 6).setFormula(sumFormula);
  }

  // ── 数値書式: 通貨 ──
  sheet.getRange(2, 2, ADCOST_INIT_MONTHS, 5).setNumberFormat('¥#,##0');
  sheet.getRange(2, 6, ADCOST_INIT_MONTHS, 1).setNumberFormat('¥#,##0');

  // ── 備考: Indeed列はAPIで自動入力される旨を色で示す ──
  sheet.getRange(2, 2, ADCOST_INIT_MONTHS, 1).setBackground('#fff9c4'); // 薄黄色=自動入力
  sheet.getRange(2, 3, ADCOST_INIT_MONTHS, 3).setBackground('#f1f8e9'); // 薄緑=手動入力
  sheet.getRange(2, 6, ADCOST_INIT_MONTHS, 1).setBackground('#e8f0fe'); // 青=計算値

  // ── 凡例コメント ──
  sheet.getRange(1, 2).setNote('黄色: fetchIndeedMonthlyCost() で自動入力');
  sheet.getRange(1, 3).setNote('緑色: 手動入力。KANOA ¥27,500/月（税込）');
  sheet.getRange(1, 4).setNote('緑色: 手動入力。キャリカミ ¥36,300/月（税込）、2026年7月〜');
  sheet.getRange(1, 5).setNote('緑色: 手動入力。Zキャリアプラットフォーム月額 ¥150,000');

  // ── 名前付き範囲: 他シートからの参照用 ──
  ss.setNamedRange('AdCost_Monthly_Data', sheet.getRange(1, 1, ADCOST_INIT_MONTHS + 1, 6));
}

// ── 月行の追加（将来分が足りなくなった場合に実行） ─────────────────────────

function addAdCostMonthRows() {
  var ss = SpreadsheetApp.getActiveSpreadsheet();
  var sheet = ss.getSheetByName('AdCost_Monthly');
  if (!sheet) { SpreadsheetApp.getUi().alert('AdCost_Monthly シートがありません'); return; }

  var lastRow = sheet.getLastRow();
  var lastYm = sheet.getRange(lastRow, 1).getValue();
  if (!lastYm) return;

  // 最終行の翌月から6ヶ月分追加
  var parts = String(lastYm).split('/');
  var y = parseInt(parts[0]), m = parseInt(parts[1]) - 1;
  var ADD_MONTHS = 6;

  for (var i = 1; i <= ADD_MONTHS; i++) {
    var d = new Date(y, m + i, 1);
    var ym = Utilities.formatDate(d, Session.getScriptTimeZone(), 'yyyy/MM');
    var row = lastRow + i;

    sheet.getRange(row, 1).setValue(ym);
    sheet.getRange(row, 3).setValue(27500);

    var isAfterJuly2026 = (d.getFullYear() > 2026) || (d.getFullYear() === 2026 && d.getMonth() >= 6);
    if (isAfterJuly2026) sheet.getRange(row, 4).setValue(36300);

    sheet.getRange(row, 5).setValue(150000);
    sheet.getRange(row, 6).setFormula('=SUM(B' + row + ':E' + row + ')');

    sheet.getRange(row, 2, 1, 5).setNumberFormat('¥#,##0');
    sheet.getRange(row, 6).setNumberFormat('¥#,##0');
    sheet.getRange(row, 2).setBackground('#fff9c4');
    sheet.getRange(row, 3, 1, 3).setBackground('#f1f8e9');
    sheet.getRange(row, 6).setBackground('#e8f0fe');
  }
}
