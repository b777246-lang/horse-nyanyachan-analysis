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
| `analysis.py` | レース内順位、評価点、コース相性、既存の特注を生データで判定 |
| `signals.py` | 狙い目の登録・判定、KOL抽出、更新済みオッズからのコメント追加 |
| `values.py` | 数値・騎手名の変換 |
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
