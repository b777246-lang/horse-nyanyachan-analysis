# S2の内部接続とWeb条件番号表示

S2共通パッケージ1.0.0を、研究照合専用としてWebへ接続する。Web出馬表の「総合評価・コース相性判定」に限り、MATCHの条件番号をNo.22／No.18等の紫太字で表示する。CSV／ダウンロードHTML列、表示・出力モード、旧推奨停止は追加しない。`research_only=true`、`prospective_ready=false`、`prospective_verified=false` を維持する。

## 入力と依存関係

```text
アップロード.getvalue()／自動検出CSV.read_bytes()
  ├─ BytesIO → 既存read_main_csv → 旧評価・特注 → 既存表示／CSV／HTML
  └─ s2_service.update_s2_audit → s2_shared.evaluate_csv_bytes
                                   └─ session_state['_s2_internal_audit']
```

元ファイルを一度だけbytesとして取得し、両経路へ同じ内容を渡す。S2には全開催・全レース・全馬を渡し、DataFrameからの指数再文字列化、画面の開催／R絞り込み、オッズ更新結果の混入を行わない。S2側はDecimal・厳密21列等の正式仕様のまま。

既存エンジンの0埋めや旧入力互換と、S2の厳密な入力拒否は別契約である。20列CSV等をS2がINVALID_INPUTとして拒否しても、既存表示・出力は従来どおり動く。旧推奨・特注・KOL・クッション値／種牡馬処理からS2を参照しない。

## 保持とキャッシュ

`_s2_internal_audit` はユーザーセッション内の最新入力1件だけを保持する。監査内容そのものを画面へ公開せず、ディスクやDBにも保存しない。承認された条件番号ラベルだけを表示用コピーへ付ける。

- `input_sha256`：元CSV全バイトのハッシュ
- `package_sha256`：実行コード7ファイル＋同梱data3ファイル、接続版のハッシュ
- `connection_version`：接続処理の版
- `status`：EVALUATED／INVALID_INPUT／ERROR
- `report`：共通公開APIの返却値をそのまま保持。エラー時はNone
- `error`：内部エラーの型と本文。正常な評価・入力拒否時はNone
- 研究／prospectiveフラグ：research_only=true、prospective関連=false

同じ入力・同じパッケージ・同じ接続版で、前回エラーがなければ再実行時に結果を再利用する。CSV切替・パッケージ変更時には置換する。エラー時は古い正常結果を使わず、次の再実行で再試行する。入力自体がなくなれば保持結果を除去する。

パッケージの欠落・manifest不一致・その他S2の例外は専用領域にERRORとして保持し、既存機能へ例外を伝播させない。入力不正をNO_MATCHとして偽装しない。S2エラーを新しい画面メッセージとして出すことも今回の対象外である。

## 同梱物と保護

`s2_shared/` の10ファイルは受領ZIPとバイト単位で一致。固定閾値・条件番号・順位・内外確認表・欠損規則を変更していない。標準ライブラリのみで、requirements.txtや環境変数を追加しない。

`docs/s2_shared/` には受領README、仕様固定書、組込ガイド、出典、元SHA256SUMSをそのまま保管する。元READMEに記載された研究テストやsamples等は、アプリ用ディレクトリには全てコピーしていない。SHA256SUMSは受領ZIP全体の一覧であり、このリポジトリでは `s2_shared/` に該当する10件をテストで検証する。

`.gitattributes` で共通コードと同梱資料の改行自動変換を無効化し、元のLF／CRLFを含むハッシュ契約を守る。共通パッケージを更新する際は、コードとdataを版としてまとめて更新し、元のチェックサムと期待値も確認する。判定器の一部だけを編集しない。

同梱の研究用保存関数はアプリから呼ばない。公開API呼出しはファイル・DBへの書込みやネットワークアクセスを行わない。

## 検証

- `python -m unittest discover -s tests -v`：既存64件＋S2接続10件。
- `tests/test_s2_integration.py`：コピー元ハッシュ、元bytes、canonical JSON、全馬保持、キャッシュ更新、旧20列／欠損拒否、例外隔離、prospectiveフラグ、アップロード、自動読込、再実行を検証する。
- 元パッケージ105テストも、同梱した実行コードをimportした状態で実行済み。研究保存テストだけは、許可範囲であるパッケージ配下の専用TemporaryDirectoryを使用し、試験後に除去する。原コード・正本・テストの内容は改変していない。
- 元CSVの研究結果と共通API出力を照合し、既存CSV／HTMLとユーザーに見えるStreamlit値も変更前後で比較する。

前向きの全頭性・取得時刻・発走前データの証明は未完了。内部接続が成功してもprospectiveフラグをtrueにしない。CSV追加・旧推奨停止は別の仕様確定と承認を要する。

## 条件番号の表示

`s2_presentation.add_s2_screen_comments()` は検証済みMATCHかつand_passed=trueの出走IDだけを照合し、固定定義順22→18→17→1→2→3→4→8で番号を並べる。複数該当は「【No.22 / No.18】」の形式。TUA190のラベルと同じ紫（#7c3aed）で表示し、元のスコア・コメント・CSV／HTML用フレームは変更しない。INVALID_INPUT／UNCONFIRMED／OUT_OF_SCOPE／NO_MATCHには番号を付けない。prospectiveフラグはfalseのまま。
