# TUA190_DIRTの内部接続とWeb研究ラベル表示

`app.py` は主CSVの元bytesを固定8条件とは別の `tua190_service.update_tua190_audit()` へ渡す。追加条件の監査結果は `_tua190_internal_audit` に保持する。承認されたWeb表示では、EVALUATEDかつMATCHの出走IDに限り、出馬表の「総合評価・コース相性判定」へ「【TUA190_DIRT・研究条件】」を紫太字で先頭表示する。`tua190_presentation.py` が表示用コピーだけを変更し、評価点・既存コメント本文・CSV・ダウンロードHTML・固定8条件の監査結果へは追加しない。research_only=true、prospective_ready=false、prospective_verified=falseを維持する。

## 受渡し

アプリと同じフォルダの `tua190_history_YYYYMMDD.sqlite` を対象日別に自動参照する。Windowsの元DBパスやPCのTARGETへアクセスしない。ファイルがない場合、芝はOUT_OF_SCOPE、ダートはUNCONFIRMEDとして保持する。古いMATCHを代替利用しない。

日付、input_csv_sha256、requested_horses、schema、SQLite quick_check、元DB最終過去日、当日／未来データ不在を読み取り専用で確認する。共通評価の前後に検証・ハッシュ比較を行い、判定中のDB変更を拒否する。SQLはread-only URIとquery_onlyを使用。固定8条件は別に評価し、このDBに依存しない。

土日混在CSVは追加条件をUNCONFIRMEDとする。土曜分と日曜分の軽量DBはそれぞれの単一日CSVで生成する。特に日曜用には土曜結果の反映が必要であり、土曜以前に作った同一履歴を黙って流用しない。

## 共通コードと生成ツール

`tua190_dirt.py` は受領ZIPとバイト一致のまま。閾値、順位、前走・キャリア・年齢、既存の監査状態の扱いを独自変更しない。受領説明書は `docs/tua190/TUA190_DIRT.md` に保存。

`tua190_history_snapshot.py` は受領版を基に、Web受渡しでの単一日CSVの要求と、Windows／POSIX共通の上書きしない公開処理だけを追加した。公開は新規hard linkの作成で行い、保存先が同時に作られても置換しない。hard link非対応の保存先では失敗し、既存データを維持する。判定条件は変更していない。元DB・CSV・既存DBを上書きしない。

```sh
python tua190_history_snapshot.py source.db 20261024.csv tua190_history_20261024.sqlite
```

生成元はPC側の元DB。元の大規模DBはクラウドに未提供。受渡し軽量DBによる実馬照合は下記の20261024分で実施済み。既存のクッション値DB・種牡馬DBは代用できない。

## 検証の範囲

`tests/test_tua190_integration.py` は人工DBを使い、受領テストのうち輸出機能に依存しない5件を移植し、Web受渡し、固定8条件の不変、DB欠損・日付／CSVハッシュ不一致・収録漏れ・古いDB・未来結果・上書き競合等を追加検証する。元同梱テストはWindows作業パスと未同梱のexport_s2_prospective.pyに依存するため、そのまま全件成功とは扱わない。新しいCSV輸出機能は作成しない。

共通評価器の鮮度判定は「対象馬の抽出履歴内の最終日」を使うため、元DBが新しくても抽出対象馬が直近開催に出ていない場合には判定不能になりうる。Web側でこの規則を緩めず、実履歴DBを受け取った際の確認事項とする。

## 実履歴による確認

リポジトリに提供された20261024.csv（468頭）とtua190_history_20261024.sqliteの対応・鮮度を検証し、共通評価器で13頭MATCHを確認した。前向きの取得証跡等を証明するものではなく、prospectiveフラグはfalseを維持する。
