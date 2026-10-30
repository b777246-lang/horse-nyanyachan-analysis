# TUA190_DIRT 研究判定

## 判定仕様

`TUA190_DIRT` はS2固定8条件とは独立した研究条件です。次をすべて満たした馬だけをMATCHにします。

- ダート
- TUA原値190以上
- 当該レース全出走馬のTUA降順競技順位3位以内
- 同じ母集団のS降順競技順位8位以内
- 直近のJRA実出走が1・2着ではない
- 直近のJRA実出走が1番人気ではない
- 当該日より前のJRA芝・ダート実出走が25戦以下
- 6歳以下

地方・海外はキャリアと前走から除きます。取消・除外は前走にもキャリアにも含めません。競走中止・失格はキャリアに含めますが、直近走の着順がNULLになるため判定不能です。履歴なしも判定不能です。

欠損、不正な指数、順位母集団の欠損、履歴不足、古い履歴DBはMATCHにしません。固定8条件の定義・閾値・監査結果には加えず、出力時だけ条件IDを集約します。

研究状態は `research_only=true`、`prospective_ready=false`、`prospective_verified=false` のままです。

## デスクトップ版

既存の操作を維持しています。

1. 元21列CSVを読み込む。
2. 「S2検証CSV出力」を押す。
3. `C:\work\s2_prospective_exports` の新規実行フォルダを確認する。

デスクトップ版は `C:\競馬DB開発\database\horse_analysis_v2_2020_2026.db` を読み取り専用で参照します。10月24・25日の判定前に、元DBへ10月17・18日のJRA結果を取り込んでください。履歴が古ければTUA190_DIRTは判定不能となり、固定8条件だけを従来どおり保存します。完了ダイアログに状態を表示します。

監査JSONの `additional_condition_report` に全馬のMATCH・NO_MATCH・OUT_OF_SCOPE・UNCONFIRMED、原値、順位、年齢、前走、キャリア、理由を保存します。metadataには履歴DBのパス・形式・SHA-256・サイズ・mtime、鮮度を保存します。

履歴鮮度は対象日より前の最終収録日が7日以内なら利用可能です。土曜・日曜で同じ基準を使い、前向き判定時に選択したDBのSHA-256と最終収録日を監査記録へ固定します。8日以上古いDBは `STALE` とし、誤抽出を避けるためMATCHにしません。

## Web版用軽量DB

PC側で対象21列CSVに限定した日付時点軽量DBを作成します。既存ファイルは上書きしません。

```powershell
python C:\work\tua190_history_snapshot.py `
  "C:\競馬DB開発\database\horse_analysis_v2_2020_2026.db" `
  "C:\path\20261024_25.csv" `
  "C:\path\tua190_history_20261024.sqlite"
```

軽量DBは現在値や現在通算だけを保存せず、対象日より前の出走を1走1行で保持します。Web側も同じ `tua190_dirt.evaluate_csv_bytes(raw_csv_bytes, snapshot_path)` を呼び出します。固定8条件の `evaluate_csv_bytes` は従来どおり別に呼び出してください。

Web側で軽量DBがない、対象日と合わない、古い、履歴が不足する場合は追加条件を表示・推薦せず、監査上UNCONFIRMEDにします。既存Web表示・既存CSVには追加しません。

## 実装ファイル

- `tua190_dirt.py`：共通の追加条件と履歴読取。
- `tua190_history_snapshot.py`：Web受渡し用軽量DB生成。
- `export_s2_prospective.py`：固定8条件と追加条件の監査・MATCH一覧を出力時に集約。
- `horse_app.py`：既存ボタンから履歴DBを渡す接続のみ。
- `test_tua190_dirt.py`：追加条件、状態、軽量DB、固定8条件との独立性を検証。

## 参考CSVの扱い

最初の参考CSVは4,597件でした。DBで照合できた4,575件のうち、44件は出走前のJRA芝・ダート通算が26〜42戦であるため、今回確定した正本条件では除外します。

追加CSV22件は、元DBに未収録だった10月17日9件・18日13件と出走IDが完全一致しました。ただし参考結果の補足であり、DB更新データではありません。元DB更新後に22件の前走・キャリア・指数を再照合します。
