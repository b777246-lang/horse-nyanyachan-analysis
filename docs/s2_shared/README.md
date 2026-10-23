# S2固定8条件 共通パッケージ 1.0.0

研究・照合専用。Desktop/Webへの組込み、S2の画面表示、CSVコメント追加は行っていない。
`prospective_ready = false`、`prospective_verified = false` を維持する。

Python 3.10以上、標準ライブラリのみ。Tkinter、Streamlit、pandas、ネット接続、TARGET、研究DBは不要。
PC内の絶対パスは実行時に参照しない。ZIPを展開したルートで以下を実行する。

```text
python -B verify_checksums.py
python -B run_tests.py
python -B -m s2_shared samples/artificial.csv > audit.json
```

`-O`は使用しない（独立SQL監査はassertを使用）。サンプルは架空の馬・騎手・指数だけで作成している。
CLI終了コードは正常評価0、入力不正2。判定不能や対象外のレースは監査結果に残す。

## 呼出し

```python
from s2_shared import evaluate_csv_bytes, evaluate_csv_text, evaluate_rows

report = evaluate_csv_bytes(csv_content)  # CP932の元バイト列
# report = evaluate_csv_text(csv_text)   # 元CSVテキスト
# report = evaluate_rows(rows)           # 各セルが元のstrの21列配列

for item in report['condition_audit']:
    print(item['entry_id'], item['condition_number'], item['state'])
```

CSVは各レースの全馬を渡す。floatになったDataFrameから指数を再文字列化しない。アップロードした元バイト列を渡す方法を推奨する。
内部の `adapter` / `detector` / `storage` は研究コードの再利用と回帰検証用。公開APIは上記3関数。

## ファイル

- `s2_shared/api.py`：書込みを行わない公開APIと監査理由の付加
- `s2_shared/adapter.py`：検証済みCSV21変換処理。importと同梱データ参照を移植
- `s2_shared/detector.py`：研究判定器の定義・順位・scope・AND処理をそのまま再利用
- `s2_shared/course_registry.py`：研究時の確認済みメタデータ表（原ファイルとバイト一致）
- `s2_shared/storage.py`：研究時の入力検証・ハッシュ保存基盤（原ファイルとバイト一致）
- `s2_shared/data/`：正本24ペア・8条件manifestの無変更コピー
- `tests/`：既存45＋39件と公開API21件。人工スナップショットのみ
- `samples/`：架空CSVとAPI監査出力
- `docs/仕様固定書.md`：正式定義、列、順位、欠損、コース、監査API
- `docs/Web版組込ガイド.md`：将来の接続方法と禁止事項
- `docs/research_verification.json`：実データ照合の件数・差異とSQL監査（実データ明細なし）
- `docs/source_provenance.json`：原コードのSHA-256と移植範囲
- `SHA256SUMS`：この一覧自身を除く同梱ファイルのSHA-256

既存研究データ、購入指数CSV、元DB、TARGETデータは同梱しない。
