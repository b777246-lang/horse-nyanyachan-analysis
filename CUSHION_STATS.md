# クッション値集計エンジン（Stage 1）

`cushion_stats.py` はStreamlit・Desktopに依存しない共通集計です。
`cushion_snapshot.py` は巨大DBを読み取り専用で開き、出馬表に含まれる馬の過去走を新しい軽量SQLiteに書き出します。既存ファイルは上書きしません。

## 画面で軽量DBを生成

Desktop版の「🗃 軽量DBを作成」、または`create_cushion_db.bat`から、元DB・出馬表CSV・保存先を選択して生成できます。コマンド入力は不要です。操作手順は`DESKTOP_CUSHION.md`を参照してください。

## コマンドによる軽量DB生成（任意）

DBのあるPCで、この2つのPythonファイルと翌日の18列形式の出馬表CSVを用意します。Python標準ライブラリだけで実行できます。

```powershell
python cushion_snapshot.py --source "C:\競馬DB開発\database\horse_analysis_v2_2020_2026.db" --entrants "20261011.csv" --output "cushion_history_20261011.sqlite"
```

CSVはUTF-8（BOM付きも可）またはCP932形式。16列目の18桁IDから日付、17列目から10桁血統登録番号を取得します。先頭ゼロを保持します。全出走馬の履歴を取得し、集計時に芝だけを対象とします。元DBの更新処理は実行しません。

軽量DBは当日未満の**過去走単位**で保持します。血統登録番号・日付の索引、要求した馬一覧、元DB収録期間、出力対象日、異常値件数を含みます。異常クッション値は丸めず原値を保持し、`anomalies`に記録します。新しい開催日には軽量DBを再生成してください。

## 共通API

```python
from cushion_stats import get_cushion_stats

result = get_cushion_stats(
    "cushion_history_20261011.sqlite",
    horse_ids=["2024102281", "2024105444"],
    race_date="20261011",
    cushion_value="9.2",
)
```

`result['horses']`は入力馬順の結果、`result['metadata']`は収録最終日等です。オプションは`official_only=True`、`track='東京'`、`distance=1600`。

## 確定した集計ルール

- 正の数・小数第1位まで。6.4以下／6.5～7.4／7.5～8.4／8.5～9.4／9.5～10.4／10.5～11.4／11.5以上。
- 同じ血統登録番号、芝、指定日より前、同じクッション区分。
- `JRA_PDF_VERIFIED`と`CSV_PROVIDED`を対象にし、出典別走数を保持。公式照合済みだけの絞り込みも可能。
- FINISHED・DEMOTEDは有効な確定着順を使用。DNF・DISQUALIFIEDは着外として対象走数と回収率母数に含め、実際の払戻金を使用。中止・失格件数も返す。
- CANCELLED・EXCLUDEDは対象外。未知・矛盾する状態は採用せず`issues`に記録。
- 勝率・連対率・複勝率は確定着順による。払戻の有無を着順の代わりにしない。
- 各走100円購入。払戻欠損・負値等がある場合、その券種の回収率は`None`。欠損を0に変換したり母数だけ減らしたりしない。
- 0走は`0-0-0-0/0`、率・回収率は`None`。UIは`None`を「—」として表示する。
- 当日のクッション値が`None`なら対象走数0、理由`cushion_unavailable`。前日の値に置換しない。
- 未登録の馬は`horse_not_in_snapshot`、対象過去走なしは`no_matching_history`。新馬とは断定しない。
- 対象日より後の日付を軽量DBに問い合わせるとエラー。収録不足を完全な履歴として扱わない。

## 検証と残る工程

```bash
python -m unittest discover -s tests -v
```

Stage 1は共通エンジンと生成処理。Stage 2でWebパネルとDesktop表示部品を追加しました。Stage 3でJRA当日値の取得を接続しました。提供されたDesktop本体へ別ウィンドウとして組み込みました。Windows実画面と実DBでの生成確認は残っています。実DBはクラウドにないため、生成処理は再現用SQLiteで検証しています。実DBでの生成・件数照合はDBのあるPCで行ってください。

## Stage 2：Webパネルの使い方

1. 芝のレース番号を選択し「🌱 クッション値別 過去成績」を開きます。
2. 前日に生成した軽量DBをアップロードします。またはアプリと同じフォルダに`cushion_history_YYYYMMDD.sqlite`を配置します。アップロードを優先します。
3. JRAが当日公表したクッション値を入力します（例：9.2）。日付・競馬場ごとに別の入力欄を保持します。
4. 全出走馬の成績が馬番順で表示されます。「成績の表示順」または列見出しで並べ替えできます。横スクロール対応です。

未公表時は空欄を維持してください。小数第2位以下はエラーとして扱います。率・回収率の算出不可は「—」。未照合、同区分の履歴なし、血統登録番号の不足を備考に表示します。ダート・全R選択時はレース別集計を表示しません。

読み込めるアップロードは32MB以内の生成済み軽量DBです。元の巨大DBをアップロードしないでください。異なる対象日のDBや破損ファイルを選択しても、既存の出馬表とオッズ操作は引き続き利用できます。翌日以降の開催には新しい軽量DBが必要です。

Stage 2では手動入力で画面と共通集計の接続を確認し、Stage 3でJRA自動取得を追加しました。

### Desktop表示部品

`cushion_desktop.CushionStatsPanel`はTkinter/ttk用の表示部品です。Streamlitには依存せず、Webと同じ`cushion_stats`と`cushion_presentation`を使います。馬番順、列見出しソート、横・縦スクロール、数値右寄せを備えています。

```python
from cushion_desktop import CushionStatsPanel

panel = CushionStatsPanel(parent_frame)
panel.pack(fill='both', expand=True)
panel.load(
    'cushion_history_20261011.sqlite',
    entrants=[{'horse_no': 1, 'horse_name': '出走馬名', 'horse_id': '2024102281'}],
    race_date='20261011', cushion_value='9.2',
    venue='東京', race_no=2, surface='芝',
)
```

提供されたTkinterの`horse_app.py`に、別ウィンドウ・例外表示・レース切替との接続を追加しました。更新方法は`DESKTOP_CUSHION.md`を参照してください。GUI実動作はこのクラウドのディスプレイなし環境では未検証です。

## Stage 3：JRA取得連携・結合テスト

Webパネルの取得方法は標準で「JRA自動取得」です。JRA公式の`https://www.jra.go.jp/keiba/baba/_data_cushion.html`から取得し、提供された`jra_cushion_extract.py`の抽出ロジックを共通モジュール`jra_cushion.py`へ移しました。

- 日本時間の当日、競馬場、月日、曜日を照合。同日の複数測定があれば最新の測定時刻を使用します。
- 公表HTMLに年がないため、年は取得日の日本時間に基づく照合であることを表示します。過去日・翌日の自動取得には利用しません。
- 前日分しかない・開催場がない場合は当日未公表／未掲載として表示。以前の成功値では補いません。
- 小数第2位以下、曜日不一致、未来の測定時刻、重複測定はエラーとして扱います。
- 取得結果は120秒キャッシュ。日付が日本時間で変わると別キャッシュになります。「クッション値を再取得」でキャッシュを解除します。
- 公表前にページを開いた場合は、公表後に再取得してください。画面操作で再実行されたときにもキャッシュ期限後なら取得します。ページを閉じた状態で定時取得するジョブはありません。
- 取得失敗時は「手動入力」へ切り替えて当日公表値を指定できます。手動値は日付・競馬場別に保持し、自動取得時には使いません。

Desktop部品にも`panel.load_jra(snapshot_path, entrants, race_date, venue='東京', race_no=2)`を追加しました。同じ取得関数・集計・表示レコードを利用します。Desktop本体からは、画面を止めない非同期取得と同じ共通集計を使う専用ウィンドウを開きます。

結合テストでは、実際のSQLiteファイルを生成し、当日CSVの血統登録番号、JRA形式HTMLの取得結果、軽量DB、Webパネル、Desktop部品のレコードを照合します。当日走の除外、中止の着外扱い、回収率、出走全馬保持、未公表・取得失敗時の旧値不使用も確認します。DesktopのGUI表示自体はディスプレイなし環境で未検証です。

実通信では2026-10-11午前2時ごろ（日本時間）、公式応答の取得・解析に成功し、当日未公表と判定しました。当日公表後の実値を使う確認と、元の実DBからの軽量DB生成はDBのあるPC・当日公表後の確認が残っています。
