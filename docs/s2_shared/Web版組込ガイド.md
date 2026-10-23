# 将来のWeb/Desktop組込ガイド

今回は組込を実施しない。この文書は次工程への引継ぎである。

1. ZIPを展開し、SHA256SUMS検証と105テストを実行する。研究原本やPC内の絶対パスは不要。
2. アプリ側から同じ `s2_shared` フォルダをimport可能な位置に配置する。同梱dataを含めてコピーし、Desktop/Webで異なる判定器を再実装しない。
3. Streamlitアップロードなら `uploaded_file.getvalue()` の元バイト列を `evaluate_csv_bytes` に渡す。DataFrameで数値変換済みの値や、画面で絞った馬だけを渡さない。
4. Desktop側も別の入力アダプターで条件を再計算せず、CSV元バイト列を同じAPIへ渡す。
5. `condition_audit` はrace_id・entry_id・condition_numberの複合キーで扱う。馬名だけでJOINしない。
6. NO_MATCHとUNCONFIRMED/INVALID_INPUT/OUT_OF_SCOPEを混同しない。CSV拒否時に一部の正常馬だけを拾って再順位付けしない。
7. 比較では条件別のstate/and_passed、親の原値・順位・閾値・passed、全登録馬ID集合、入力SHA、正本SHA、パッケージ版を照合する。APIのencode（canonical JSON）で同入力の完全一致も確認できる。
8. アプリ上の表示やCSV追加を実装する際は別承認を得る。今回の研究結果を実運用の推奨として自動表示しない。旧スコア・★特注★へS2を加点・混在させない。

公式時刻・取得証跡・全頭性等の前向き検証は未完了。prospective_ready/prospective_verifiedをtrueへ変更しない。内部モジュールのdefsやコース表を上書きして研究結果に合わせない。

同じCSVに対する照合例：

```python
from s2_shared import evaluate_csv_bytes
from s2_shared.storage import encode

desktop_audit = evaluate_csv_bytes(original_bytes)
web_audit = evaluate_csv_bytes(original_bytes)
assert encode(desktop_audit) == encode(web_audit)
```

ZIPには実馬の購入指数CSV・研究DB・TARGETデータを含まない。添付の架空fixtureと固定manifestで条件・境界・状態の扱いを理解、テストできる。
