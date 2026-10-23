# 開発と役割分担

リポジトリのディレクトリから `streamlit run app.py` で起動する。
依存関係は `requirements.txt`。テストはネットワークを使わず、次のコマンドで実行できる。

```sh
python -m unittest discover -s tests -v
```

| ファイル | 役割 |
| --- | --- |
| `app.py` | Streamlitの画面、セッション状態、ボタン操作 |
| `data_loader.py` | 最新CSVの選択、読込、列名の正規化、コース成績・外部コメントの読込 |
| `config.py` | KOL・F-UP・指数評価・コース相性・特注の設定と設定読込インターフェース |
| `analysis.py` | 共通の数値・レース内順位を準備し、旧推奨と特注を独立評価して互換合成 |
| `legacy_recommendations.py` | 旧推奨の指数評価・調教加点・コース相性・旧ラベル |
| `recommendation_composition.py` | 独立した旧推奨・特注結果の保持と従来スコア／コメントの互換合成 |
| `signals.py` | 狙い目の登録・判定、KOL抽出、更新済みオッズからのコメント追加 |
| `values.py` | 数値・騎手名・開催場略称の共通変換 |
| `formatting.py` | 画面用CSS、枠色、順位色、コメントのHTML装飾 |
| `export.py` | TARGET用コメントの整形、CSV、通常・KOL HTMLレポート |
| `odds_service.py` | 全レース更新、失敗時の保持、レース別キャッシュの反映 |
| `jra_odds.py` | JRAへの通信とページ解析（今回変更なし） |

処理は `CSV → 列名正規化 → 数値判定 → オッズ反映・追加判定 → 表示／出力` の順。
`AnalysisBatch.frame` は数値・プレーンテキストを保持する。`notes` は順位とコメントの
生データを保持し、HTMLは `formatting.py` で生成する。TARGET用CSVのコメントに
HTMLタグを付加しない。従来のTARGET向け記号除去と、F-UP追加コメントの扱いも維持する。

## 将来のDB設定読込

現在は `load_settings()` が `LocalSettingsProvider` から従来の既定値を読む。
DB接続はまだ実装していない。将来のアダプターは `SettingsProvider.load()` を実装し、
`AnalysisSettings` を返す。`app.py` の読込を `load_settings(DbSettingsProvider(...))`
に変更すれば、分析、KOL判定、F-UP、画面の条件説明、HTML抽出に同じ設定を渡せる。

DBの数値をKOL設定へ変換するときは `Decimal(str(value))` を使う。
設定はタスクごとの読込結果として渡し、共有の既定値を変更しない。
不正な設定や読込エラーは明示的にエラーにする。DB障害時に古い条件を利用するかは、
実際のDB連携時に決める。現在はDBへの接続、認証、テーブルの作成を行わない。

## 狙い目の追加

単純な条件の組合せは `config.py` の `special_rules` に追加する。
条件はANDで評価し、`eq`、`ne`、`ge`、`le`、`in`、`not_contains_any` を利用できる。

```python
SpecialRule(
    key="new_arms_signal",
    comment="★新狙い目★",
    conditions=(Condition("arms", "ge", 150), Condition("surface", "eq", "芝")),
    score=1,
    enabled=True,
)
```

分析時には、開催場、条件、芝／ダート、距離、枠、全指数と順位、F-UPと順位、
馬名、馬番、レースID、騎手、KOLオッズを使える。
追加した判定はコメントとスコアへ反映され、既存の表示・CSV・HTMLに流れる。
新しい列が必要なら `data_loader.py` の正規化と分析の入力を拡張する。

独自の計算が必要な場合は `SignalDefinition` の判定関数を追加し、
`DEFAULT_REGISTRY.with_signal(...)` で登録する。
`pre` は指数評価時、`live` はオッズ取得後の判定。`live` の判定関数は
数値を保持するフレームの行（例：`実オッズ`、`人気`、`厩舎F-UP2`）を受け取る。
独自レジストリは分析、追加コメント、表示へ同じものを渡す。
`live` コメントの追加でスコアは変更しない（従来のF-UP動作を維持）。
`kol`・`fup` は予約キーで、その他のキーも重複させない。

## 既存動作の検証

`tests/fixtures/refactor/` は整理前の2日分の入力と出力ハッシュを保持する。
10月3日の349頭と10月4日の362頭、計711頭について、指数評価・コース相性・
コメント・並び順を含むCSV／通常HTML／KOL HTMLを、初期状態、オッズ反映後、
スコア順で整理前と完全一致するか確認する。最新CSVが入れ替わっても検証資料は残る。
既定条件や出力仕様を意図的に変える場合は、不一致の理由を確認してから基準を更新する。

KOL境界、F-UP、設定差替え、狙い目追加、全レース更新の失敗継続、CSVのHTML除去、
KOL抽出と既存出力もテストする。実JRA通信は単体テストでは模擬する。


## 出馬表CSVの血統登録番号

新形式は15列目=KOLオッズ、16列目=18桁レースID、17列目=10桁血統登録番号、
18列目=騎手。血統登録番号は先頭のゼロを保持する文字列で扱い、画面には追加せず、
分析データとTARGET用CSVの `血統登録番号` 列に保持する。将来の過去走照合に利用する。
旧形式（17列目=騎手）も読み込める。17列目の値から形式を識別し、同じCSV内で
血統登録番号と騎手名が混在する場合は列ずれとして停止する。

## 年齢入力

新形式CSVの19列目を`age`としてWeb・Desktop共通で保持します。欠損・旧形式では空欄。血統登録番号と騎手の位置は変わりません。年齢は出馬表・HTML・既存TARGET用CSVには追加表示しません。

## 内外回りの入力（将来用）

出馬表CSVの21列目を `course_layout` として保持する。外回りは「外」、空欄は指定なしとして扱い、内回りとは推定しない。旧20列以下のCSVでは空文字となる。現在の判定・スコア・出馬表・TARGET用CSV・クッション値／種牡馬成績の条件には使用しない。将来のS2入力へ接続する処理は未実装。

## 旧推奨と特注の分離（第1段階）

`analyze_csv()` は入力正規化・出走ID整備・指数順位を共通処理として維持し、各馬につき `evaluate_legacy()` と `SignalRegistry.evaluate(stage="pre")` をそれぞれ呼ぶ。特注条件は `signals.py`／`config.py` のままで、旧推奨をimportせず、旧スコアも参照しない。旧推奨も特注の条件・登録処理を参照しない。東京芝2000特注の馬体重文言は手動確認用のまま、自動条件を追加していない。

`AnalysisBatch.recommendations[original_index]` に `RecommendationParts` を保持する。`legacy` は旧推奨だけの素点・根拠・コース相性フラグを持つ `LegacyRecommendation`、`specials` は順序を保った `SignalMatch` のtuple。旧推奨へ特注の点を直接書き込まず、合成時に `legacy.score + sum(match.score)` を既存のframe.scoreへ出力する。最終ラベルは合成点と旧相性フラグに従い、従来の優先順位で `recommendation_label()` が返す。

合成コメントは従来どおり、旧ラベル＋特注本文（登録順）＋指数・調教の根拠＋コース相性。外部コメントはその後に付加する。既存の `frame` の列・順序・値、`notes` のキー・値は維持し、独立結果をCSV列へ追加しない。表示・TARGET整形・HTML、liveのF-UP追加、KOL処理は既存のまま。`AnalysisBatch(frame, notes)` の2引数構築も引き続き可能。

旧推奨の評価呼出しは `analysis.analyze_csv()` の1箇所、旧ラベルの呼出しは互換合成内の1箇所に限定する。従来の `analysis.parse_racetrack` と `analysis.get_course_compatibility` のimport経路も再公開により維持する。F-UPはオッズ反映後に既存のliveレジストリが評価し、事前の `recommendations` へ混ぜない。

今回は停止フラグ・表示／CSVモード・S2を追加しない。将来の停止時にはオーケストレーションと互換合成の旧結果必須構造、トップレベルimportと互換再公開、コースCSV読込、score順ソートを整理する必要がある。共通順位や特注条件を旧モジュールと一緒に削除しない。

追加の `tests/test_recommendation_separation.py` では7事前特注の成立／不成立、複数特注の順序と互換加点、旧閾値・コース優先、独立結果保持、F-UP追加／解除、依存方向、Streamlitのソート／リセットとCSVを検証する。既存回帰基準のハッシュは更新しない。

## S2の非表示接続

元の主CSVバイト列を、既存のDataFrame読込と独立した `s2_service.update_s2_audit()` へ渡す。共通パッケージ `s2_shared/` は受領版を無変更で使用し、結果は専用session_stateだけに保持する。旧スコア・特注・コメント・画面・CSV／HTMLへは接続しない。正式入力の拒否やS2の障害は旧機能へ伝播させない。詳細は `S2_INTERNAL.md`。

## TUA190_DIRTの非表示接続

主CSV元bytesを `tua190_service` へ別途渡し、日付別のTUA190専用軽量DBをread-onlyで参照する。監査は専用session_stateへ保持し、検証済みMATCHのみWebの「総合評価・コース相性判定」に研究条件ラベルとして表示する。表示用コピーだけを変更し、固定8条件・旧評価点・特注・CSV／ダウンロードHTMLは変更しない。DB欠損・不一致・古い履歴は判定不能とし、ラベルを付けない。詳細は `TUA190_INTERNAL.md`。
