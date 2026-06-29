/**
 * Migration v5: 流入経路列追加 + KANOA/キャリカミシート作成
 *
 * 変更内容:
 *   - Candidates: 列U (21) に「流入経路」を追加
 *   - README: Slackフォーマットに「流入経路」行を追記
 *   - KANOA シート新規作成
 *   - キャリカミ シート新規作成
 *
 * 実行方法: GASエディタで migrateV5 を選択して「実行」
 */

var MIGRATION_V5_KEY = 'schema_version';
var MIGRATION_V5_VALUE = 5;

function migrateV5() {
  var ss = SpreadsheetApp.getActiveSpreadsheet();
  var props = PropertiesService.getScriptProperties();
  var current = parseInt(props.getProperty(MIGRATION_V5_KEY) || '0', 10);

  if (current >= MIGRATION_V5_VALUE) {
    SpreadsheetApp.getUi().alert('v5マイグレーション済みです（スキップ）');
    return;
  }

  _addAcquisitionSourceColumn_(ss);
  _updateReadmeSlackFormat_(ss);
  _createKanoaSheet_(ss);
  _createCarikamSheet_(ss);

  props.setProperty(MIGRATION_V5_KEY, String(MIGRATION_V5_VALUE));
  SpreadsheetApp.getUi().alert('v5マイグレーション完了');
}

// ── Candidates: 流入経路列追加 ──────────────────────────────────────────────

function _addAcquisitionSourceColumn_(ss) {
  var sheet = ss.getSheetByName('Candidates');
  if (!sheet) throw new Error('Candidatesシートが見つかりません');

  var headers = sheet.getRange(1, 1, 1, sheet.getLastColumn()).getValues()[0];
  if (headers.indexOf('流入経路') !== -1) return; // 冪等

  var col = headers.length + 1; // 末尾に追加
  sheet.getRange(1, col).setValue('流入経路');
  sheet.getRange(1, col).setFontWeight('bold');
}

// ── README: Slackフォーマット更新 ───────────────────────────────────────────

function _updateReadmeSlackFormat_(ss) {
  var sheet = ss.getSheetByName('README');
  if (!sheet) return;

  var data = sheet.getDataRange().getValues();
  for (var r = 0; r < data.length; r++) {
    for (var c = 0; c < data[r].length; c++) {
      var cell = String(data[r][c]);
      // 既に更新済みならスキップ
      if (cell.indexOf('流入経路') !== -1) return;
      // Slackフォーマット欄を発見したら更新
      if (cell.indexOf('【成約報告】') !== -1) {
        var updated = cell.replace(
          '業種（職種）:',
          '流入経路：Indeed / KANOA / キャリカミ\n業種（職種）:'
        );
        sheet.getRange(r + 1, c + 1).setValue(updated);
        return;
      }
    }
  }
}

// ── KANOAシート作成 ────────────────────────────────────────────────────────

function _createKanoaSheet_(ss) {
  if (ss.getSheetByName('KANOA')) return; // 冪等

  var sheet = ss.insertSheet('KANOA');

  var headers = [
    '受信日',
    '氏名',
    'ふりがな',
    '生年月日',
    '年齢',
    '性別',
    '電話番号',
    'メールアドレス',
    '住所',
    '最寄駅',
    '最終学歴',
    '現職種 / 職歴',
    '転職理由',
    '希望年収',
    '希望勤務地',
    '希望職種',
    '面談ステータス',
    '面談日',
    '結果',
    '入社決定日',
    '備考',
  ];

  _writeSheetHeaders_(sheet, headers);
  _setKanoaValidation_(sheet);
}

function _setKanoaValidation_(sheet) {
  // 面談ステータスのドロップダウン (Q列 = 17)
  var statusRule = SpreadsheetApp.newDataValidation()
    .requireValueInList(['未調整', '調整中', '完了', 'キャンセル', '対象外'], true)
    .build();
  sheet.getRange(2, 17, 500, 1).setDataValidation(statusRule);

  // 性別 (F列 = 6)
  var genderRule = SpreadsheetApp.newDataValidation()
    .requireValueInList(['男性', '女性', 'その他'], true)
    .build();
  sheet.getRange(2, 6, 500, 1).setDataValidation(genderRule);
}

// ── キャリカミシート作成 ───────────────────────────────────────────────────

function _createCarikamSheet_(ss) {
  if (ss.getSheetByName('キャリカミ')) return; // 冪等

  var sheet = ss.insertSheet('キャリカミ');

  var headers = [
    '受信日',
    '氏名',
    'ふりがな',
    '生年月日',
    '年齢',
    '性別',
    '電話番号',
    'メールアドレス',
    '住所',
    '最寄駅',
    '最終学歴',
    '現職種 / 職歴',
    '転職理由',
    '希望年収',
    '希望勤務地',
    '希望職種',
    '面談ステータス',
    '面談日',
    '結果',
    '入社決定日',
    '備考',
  ];

  _writeSheetHeaders_(sheet, headers);
  _setCarikamValidation_(sheet);
}

function _setCarikamValidation_(sheet) {
  var statusRule = SpreadsheetApp.newDataValidation()
    .requireValueInList(['未調整', '調整中', '完了', 'キャンセル', '対象外'], true)
    .build();
  sheet.getRange(2, 17, 500, 1).setDataValidation(statusRule);

  var genderRule = SpreadsheetApp.newDataValidation()
    .requireValueInList(['男性', '女性', 'その他'], true)
    .build();
  sheet.getRange(2, 6, 500, 1).setDataValidation(genderRule);
}

// ── 共通ヘルパー ─────────────────────────────────────────────────────────────

function _writeSheetHeaders_(sheet, headers) {
  var range = sheet.getRange(1, 1, 1, headers.length);
  range.setValues([headers]);
  range.setFontWeight('bold');
  range.setBackground('#e8f0fe');
  sheet.setFrozenRows(1);

  // 列幅を読みやすく
  var widths = {
    1: 90,   // 受信日
    2: 100,  // 氏名
    3: 100,  // ふりがな
    4: 90,   // 生年月日
    5: 50,   // 年齢
    6: 60,   // 性別
    7: 110,  // 電話番号
    8: 160,  // メールアドレス
    9: 180,  // 住所
    10: 100, // 最寄駅
    11: 120, // 最終学歴
    12: 160, // 現職種/職歴
    13: 160, // 転職理由
    14: 80,  // 希望年収
    15: 100, // 希望勤務地
    16: 100, // 希望職種
    17: 90,  // 面談ステータス
    18: 90,  // 面談日
    19: 80,  // 結果
    20: 90,  // 入社決定日
    21: 200, // 備考
  };
  Object.keys(widths).forEach(function(col) {
    sheet.setColumnWidth(parseInt(col), widths[col]);
  });
}
