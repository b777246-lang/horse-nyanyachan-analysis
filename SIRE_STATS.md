# Web版への組み込み結果（2026-10-18）

既存の「クッション値別 過去成績」パネルで、「出走馬別成績」「種牡馬別成績」の2タブを表示します。取得方法・当日値・公式照合済みのみ設定は共通で、JRAを二重取得しません。20列目の父名は種牡馬タブにだけ表示し、既存の出馬表・HTML・TARGET用CSVには追加しません。

Webで使うファイルは、通常の`YYYYMMDD.csv`（20列目は父名）、従来の`cushion_history_YYYYMMDD.sqlite`、追加の`sire_history_YYYYMMDD.sqlite`です。いずれも`app.py`と同じフォルダに置けば日付別に自動読込します。種牡馬DBと出馬表は対象日が完全一致する必要があります。種牡馬DBがなくても既存の出走馬別タブは使えます。ダート・全Rは従来どおり対象外です。

10/18用の父名入りCSVと受領した種牡馬DBを配置しました。父名を除く既存19列は変更していません。過去日データに依存するテストは`tests/fixtures/daily`に固定し、本番の日付CSV削除で壊れないようにしました。

検証：全53テスト合格。芝248頭×7帯×公式ON/OFFの3,472件を独立SQLと照合し、件数・着別度数・回収率が一致。元の個体別集計関数、既存クッション値DB、JRA取得、軸馬・特注コードは未変更。Streamlit起動・HTTP応答・AppTestによるタブ操作も確認しました。

今回、Desktop担当の改修済みGUI本体は同梱されていないため、本リポジトリのDesktop GUIを上書きしていません。以下は提供元の申し送り原文であり、Desktop側の26テスト等は提供元による結果です。こちらでのWeb側検証と区別してください。

---

# 種牡馬別成績：Desktop導入・Web担当への引き継ぎ

## 実装した範囲

既存のクッション値画面に「出走馬別成績」「種牡馬別成績」の2タブを用意しました。既存の出走馬別集計・JRA取得処理・判定条件は維持しています。元DB・出馬表・既存軽量DBは変更しません。

CSVは従来の列順のまま、19列目=年齢、20列目=種牡馬名。父名は既存出馬表に表示せず、種牡馬タブだけに表示します。18・19列の旧CSVも読めます。父名が空欄なら血統登録番号で元DBを参照し、過去走もなければ「不明」にします。不明を0走扱いしません。CSVと元DBの父名矛盾・表記衝突は生成を停止します。

父はID未提供のため前後空白を除いた名称の完全一致です。NFKCは衝突検出にのみ使い、名称の自動統合は行いません。同名別種牡馬を識別するには父ID付きソースが必要です。

## Desktopでの利用

1. 20列の出馬表CSVを読み込みます。
2. 「クッション値別成績」を開きます。
3. 「種牡馬DBを作成」から元DB・当日の出馬表・新しい保存先を指定します。既存ファイルは上書きしません。
4. 「種牡馬別成績」タブを選びます。元のタブと同じ自動取得値／手動値、公式照合済み限定設定を使います。

`C:\work\sire_history_YYYYMMDD.sqlite`があれば自動認識します。別の場所に生成した場合は「種牡馬DBを選択」で指定します。元DBは生成時だけ参照します。GUIはバックグラウンド生成、検索は専用軽量DBを読み取り専用で行います。元の個体別軽量DBが未選択でも種牡馬タブは使えます。

10月18日用は`C:\work\sire_history_20261018.sqlite`を生成済みです。当日値は含みません。7区分をすべて用意するので、JRA公表前に生成できます。

コマンドでの生成も可能です。

```powershell
python -B sire_snapshot.py --source "C:\競馬DB開発\database\horse_analysis_v2_2020_2026.db" --entrants "C:\Users\Owner\OneDrive\Desktop\20261018種牡馬入り.csv" --output "C:\work\sire_history_20261018.sqlite"
```

## 共通集計とDB仕様

- `sire_snapshot.read_sire_entrants()`：出馬表の登録番号・父名・コースを取得。競馬場はTARGET IDの場コードから決定。
- `sire_snapshot.create_sire_snapshot()`：当日の父×競馬場×芝距離に一致する全産駒の過去走を抽出。出走馬本人だけに限定しません。
- `sire_stats.get_sire_stats()`：対象日完全一致を確認し、日付・父・場・距離・区分・公表状態で検索。同父は1回だけ集計。
- `sire_presentation.build_sire_records()`：Web/Desktop共通の表示値を作成。
- `sire_desktop.SireStatsPanel`：Desktop用表示部品。
- `sire_web.render_sire_tab()`：クラウド担当が既存Webへ組み込むためのアダプター。単独でJRA取得はしません。

専用DB形式版は`sire-1`。`entrant_sires`、`scopes`、`sire_history`、`anomalies`、`metadata`を持ちます。`sire_history.target_id`を一意にし、索引`ix_sire_course_band_date(sire_name,venue,distance,cushion_band,race_date)`で検索します。

既存の`cushion_stats.aggregate_history()`と`cushion_band()`を利用します。同じ競馬場×芝×距離×帯、対象日前のみ。内外・直線・A/B/C/Dでは分割しません。日付を残すため未来走を混入させません。取消・除外は対象外、中止・失格は着外、降着・同着は保存確定着順と実払戻で集計します。CSV_PROVIDEDはOFFで含め、ONではJRA_PDF_VERIFIEDだけを使用します。

父名不明、DB収録対象外、収録コース外、当日値未取得は成績「—」と理由を表示。一致走が本当に0の場合だけ`0-0-0-0/0`です。対象走数5未満は参考値の注記があります。

生成は同じ保存先フォルダに一時DBを作成し、完全生成・整合性検証後に新規ファイルとして公開します。Windowsは既存先を置換しないrename、その他はno-replaceのhard linkです。既存正常版は置換しません。更新は別名生成・検証後に「種牡馬DBを選択」で切り替えてください。生成失敗時は旧版が残ります。

## Web側の組み込み（クラウド担当）

公開Webのコード・GitHubはこの作業では変更していません。ローカルの`data_loader.py`をWeb版へ丸ごと上書きしないでください。Web側には別途年齢対応が入っているため、既存処理へ20列目のマッピングだけを追加します。

```python
# normalize_main_frame() の列名変換で追加
names[19] = 'sire_name'
# 旧CSVでは空欄を用意し、fillna('').astype(str).str.strip()する
```

既存Webパネルの取得・手動入力を1回だけ行い、その後で2タブを作成します。既存の個体別表示処理を最初のタブへそのまま残し、2番目に次を接続します。

```python
from sire_web import render_sire_tab

entrants = [
    {'horse_no': row['horse_no'], 'horse_name': row['horse_name'],
     'horse_id': row['horse_id'], 'sire_name': row.get('sire_name', '')}
    for _, row in selected.iterrows()
]
horse_tab, sire_tab = st.tabs(['出走馬別成績', '種牡馬別成績'])
with horse_tab:
    # 既存の軽量DB読込・出走馬別成績表示を維持
    ...
with sire_tab:
    render_sire_tab(entrants, day, value, venue=venue,
                    distance=int(selected['distance'].iloc[0]),
                    surface='芝', official_only=official_only)
```

`value`は既存処理で確定した当日値。未取得ならNoneです。前日値や別会場値は代用しません。距離がレース内で一意であることを検証してください。ダート・全Rの既存早期returnはそのまま残します。専用DBは`app.py`と同じフォルダに配置します。個体別DBのアップロード処理は維持し、種牡馬DBの差し替えUIを追加する場合は別キー・一時ファイル・読み取り専用を使ってください。

本番Webでのタブ切替・スマートフォン表示・Streamlit実セッションの検証と公開反映はクラウド担当の作業です。ローカルではアダプターから返す表示レコードとDesktopの実ウィジェットのレコード一致を検証しています。

## 検証結果

2026年10月18日の20列CSV、450頭すべて父名取得。芝248頭。専用DBは202コース条件、6,898頭走、1,671,168バイト、生成約7.56秒。

- 元DB・専用DBの全明細比較：不一致0件。
- 芝248頭×7区分×公式照合ON/OFFの3,472件：独立計算した着別度数・率・回収率と不一致0件。
- 既存の保存済み344頭×7区分2,408件：変更前の個体別結果と一致。
- 実際の既存Desktop本体を変更前後で読み込み、450頭の出馬表データ一致・父名非表示を確認。
- 一時DBの26テスト：合格。0走／不明／旧CSV／父名矛盾／同着／降着／中止／事後失格／払戻NULL／未来走／公開失敗／区分境界／索引／Notebook切替を含む。
- 芝20レースの専用検索：平均18.1ms、最大32.9ms（入力9.4は性能テスト用で当日の公表値を意味しません）。
- 元DB、元CSV、既存軽量DB、個体別集計エンジン等の保護対象はSHA-256で変更なし。

詳細証拠：`sire_feature_20261018/real_validation.json`、`gui_regression.json`、`query_timing.json`。

## 変更ファイルと復旧

既存ファイルの変更は`data_loader.py`、`horse_app.py`、`cushion_desktop_window.py`、`cushion_snapshot_app.py`の4つです。既存の`cushion_stats.py`、`cushion_snapshot.py`、`cushion_desktop.py`、JRA取得処理は変更していません。

変更前4ファイルは`C:\work\sire_feature_20261018\before`に退避しています。復旧時は4ファイルを戻してアプリを再起動してください。専用DB・追加モジュールは既存機能から参照されなくなります。元DBや既存軽量DBの復元は不要です。
