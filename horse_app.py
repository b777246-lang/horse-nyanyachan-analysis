import glob
import os
import re
import unicodedata
from decimal import Decimal, InvalidOperation
from datetime import datetime
from html import unescape
from html.parser import HTMLParser
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, ttk
from tkinter import font as tkfont
import pandas as pd
from data_loader import normalize_main_frame
from cushion_desktop_window import CushionViewerWindow
from cushion_snapshot_app import SnapshotCreator


# ============================================================
# TARGET 単勝オッズ取得
# ============================================================
TARGET_ROOT = Path(r"C:\TFJV")

RT_RECORD_START = 43
RT_HORSE_RECORD_SIZE = 8
RT_MAX_HORSES = 28
KOL_HIGHLIGHT_COLOR = "#ffd699"


def is_finish_up_special(row):
    condition = unicodedata.normalize("NFKC", str(row.get("class_name", "")))
    condition = re.sub(r"[\s*＊]", "", condition)
    # Web版と同じく、年齢などを含む条件名でも対象クラスを判定する。
    allowed_class = any(
        name in condition for name in ("未勝利", "1勝クラス", "2勝クラス", "3勝クラス")
    ) or re.fullmatch(
        r"(?:未勝利|[123]勝(?:クラス|C)?|500万下|1000万下|1600万下)", condition
    ) is not None
    try:
        points = float(row.get("厩舎finish-up", 0))
        popularity = int(row.get("actual_popularity") or 0)
    except (ValueError, TypeError):
        return False
    return (row.get("venue") in {"阪神", "京都", "中山", "東京", "中京"}
            and allowed_class and 6 <= points <= 7 and popularity in (1, 2))


def refresh_finish_up_comment(row):
    # 基本コメントから毎回作り直し、人気変動時に追加・解除する。
    base = row["base_comment"]
    row["総合評価・コース相性判定"] = (
        "★F-UP特注★" + (" / " + base if base else "")
        if is_finish_up_special(row) else base
    )


def clean_text_for_target(value):
    """装飾タグと絵文字を除去し、特注コメント本文と★は保持する。"""
    if not isinstance(value, str):
        return value

    class CommentTextParser(HTMLParser):
        def __init__(self):
            super().__init__(convert_charrefs=True)
            self.parts = []

        def handle_data(self, data):
            self.parts.append(data)

        def handle_starttag(self, tag, attrs):
            if tag.lower() == "br":
                self.parts.append(" ")

    parser = CommentTextParser()
    parser.feed(unescape(value))
    parser.close()
    text = "".join(parser.parts)
    # ★（U+2605）はCP932で出力可能なので除去対象から外す。
    text = re.sub("[\U00010000-\U0010ffff\u2600-\u2604\u2606-\u27ff\ufe0f\u200d]", "", text)
    return text.strip()


def resolve_race_date(rows, source_name):
    """レースIDの開催日を優先し、旧CSVでは有効な8桁の日付名を使う。"""
    def valid_date(value):
        if not re.fullmatch(r"\d{8}", value):
            return False
        try:
            datetime.strptime(value, "%Y%m%d")
            return True
        except ValueError:
            return False

    dates = set()
    for row in rows:
        race_id = str(row.get("race_id", "")).strip()
        if re.fullmatch(r"\d{16}(?:\d{2})?", race_id) and valid_date(race_id[:8]):
            dates.add(race_id[:8])
    if dates:
        return next(iter(dates)) if len(dates) == 1 else None
    dates = {value for value in re.findall(r"(?<!\d)\d{8}(?!\d)", source_name)
             if valid_date(value)}
    return next(iter(dates)) if len(dates) == 1 else None


def load_wakuban_colors():
    path = Path(__file__).with_name("wakuban_colors.csv")
    try:
        df = pd.read_csv(path, encoding="utf-8-sig")
    except UnicodeDecodeError:
        df = pd.read_csv(path, encoding="cp932")
    return {int(row.iloc[0]): str(row.iloc[1]).strip() for _, row in df.iterrows()}


def wakuban_cell_colors(wakuban, colors):
    bg = colors.get(wakuban, "white")
    return bg, "white" if wakuban in (2, 3, 4) else "black"


def normalize_jockey(name):
    name = re.sub(r"\s+", "", unicodedata.normalize("NFKC", str(name)))
    # TARGETのルメール表記だけは頭文字を省略している。
    return "C.ルメール" if name == "ルメール" else name


def load_qualified_jockeys():
    path = Path(__file__).with_name("jockey_top3rate_over0.25.csv")
    df = pd.read_csv(path, encoding="utf-8-sig")
    rates = pd.to_numeric(df.iloc[:, 1], errors="coerce")
    return {normalize_jockey(n) for n in df.loc[rates >= 0.25].iloc[:, 0]}


def kol_gap_analysis(row, qualified_jockeys):
    """未取得・不正オッズは判定対象外。境界値は十進数で比較する。"""
    try:
        kol = Decimal(str(row.get("KOLオッズ", "")))
        actual = Decimal(str(row.get("単勝オッズ", "")))
        if not kol.is_finite() or not actual.is_finite() or kol <= 0 or actual <= 0:
            return None, False
        gap = (actual - kol) / kol * 100
        popularity = int(row.get("actual_popularity") or 0)
    except (InvalidOperation, ValueError, TypeError):
        return None, False
    eligible = (kol < 50 and 150 <= gap <= 450 and popularity >= 5
                and normalize_jockey(row.get("jockey", "")) in qualified_jockeys)
    return gap, eligible


def _target_ascii(data):
    return data.decode("ascii", errors="ignore").strip()


def _target_odds(raw):
    s = _target_ascii(raw)
    if not s.isdigit():
        return None
    n = int(s)
    return n / 10.0 if n > 0 else None


def read_target_rt_win_odds(path):
    """TARGET RT...1.DAT から {馬番: 単勝オッズ} を返す。"""
    return {horse: values["odds"] for horse, values in read_target_rt_win_data(path).items()}


def read_target_rt_win_data(path):
    """単勝レコードのオッズ4桁・実人気2桁を読み込む。"""
    data = Path(path).read_bytes()
    if len(data) < RT_RECORD_START or data[:2] != b"O1":
        return {}

    result = {}
    for slot in range(RT_MAX_HORSES):
        pos = RT_RECORD_START + slot * RT_HORSE_RECORD_SIZE
        rec = data[pos:pos + RT_HORSE_RECORD_SIZE]
        if len(rec) < RT_HORSE_RECORD_SIZE:
            break
        horse_s = _target_ascii(rec[:2])
        if not horse_s.isdigit():
            continue
        horse_no = int(horse_s)
        if horse_no <= 0:
            continue
        odds = _target_odds(rec[2:6])
        if odds is not None:
            popularity = _target_ascii(rec[6:8])
            result[horse_no] = {
                "odds": odds,
                "popularity": int(popularity) if popularity.isdigit() else None,
            }
    return result


TARGET_VENUE_CODES = {
    "札幌": "01", "函館": "02", "福島": "03", "新潟": "04",
    "東京": "05", "中山": "06", "中京": "07", "京都": "08",
    "阪神": "09", "小倉": "10",
}


def find_target_rt_file(target_root, yyyymmdd, venue, race_no):
    """
    日付・競馬場・Rから、そのレースの RT...1.DAT を特定する。
    開催回/開催日はファイル名を推測せず、実在ファイルを検索する。
    """
    venue_code = TARGET_VENUE_CODES.get(venue)
    if not venue_code:
        return None

    folder = Path(target_root) / "RT_DATA" / yyyymmdd[:4] / yyyymmdd[4:8]
    if not folder.exists():
        return None

    # RT + YYYYMMDD + 場コード + 開催回2桁 + 開催日2桁 + R2桁 + "1.DAT"
    pat = re.compile(
        rf"^RT{re.escape(yyyymmdd)}{venue_code}\d{{4}}{int(race_no):02d}1\.DAT$",
        re.IGNORECASE,
    )
    matches = [p for p in folder.glob("RT*1.DAT") if pat.match(p.name)]
    return matches[0] if len(matches) == 1 else None



class HorseApp(tk.Tk):

    def __init__(self):
        super().__init__()
        self.title(
            "競馬指数 総合分析アプリケーション (推印対応・レース別表示版)"
        )
        self.geometry(f"{int(self.winfo_screenwidth() * 0.9)}x{int(self.winfo_screenheight() * 0.85)}")
        if os.name == "nt":
            self.state("zoomed")  # タスクバーを除く作業領域に合わせる

        style = ttk.Style()
        style.theme_use("clam")

        # コース別成績データの事前読み込み
        self.load_course_data()
        self.qualified_jockeys = load_qualified_jockeys()
        self.wakuban_colors = load_wakuban_colors()

        # 外部コメント用データフレーム
        self.ext_comment_df = None

        # --- 上部：ファイル読み込み・操作パネル ---
        control_frame = ttk.LabelFrame(self, text=" データ操作・出力 ", padding=10)
        control_frame.pack(fill="x", padx=15, pady=10)

        kol_output_frame = ttk.Frame(control_frame)
        kol_output_frame.pack(side="bottom", fill="x", pady=(6, 0))
        self.kol_html_btn = ttk.Button(
            kol_output_frame,
            text=" KOL該当馬HTML出力 ",
            command=self.export_kol_html,
            state="disabled",
        )
        self.kol_html_btn.pack(side="right", padx=5)
        self.cushion_window = None
        self.cushion_btn = ttk.Button(kol_output_frame, text=" 🌱 クッション値別成績 ", command=self.open_cushion_viewer)
        self.cushion_btn.pack(side="left", padx=5)
        self.snapshot_window = None
        self.snapshot_btn = ttk.Button(kol_output_frame, text=" 🗃 軽量DBを作成 ", command=self.open_snapshot_creator)
        self.snapshot_btn.pack(side="left", padx=5)

        self.load_btn = ttk.Button(
            control_frame,
            text=" 📂 指数CSVファイルを読み込む ",
            command=self.load_csv,
        )
        self.load_btn.pack(side="left", padx=5)

        self.odds_btn = ttk.Button(
            control_frame,
            text=" 💴 オッズ更新 ",
            command=self.update_win_odds,
            state="disabled",
        )
        self.odds_btn.pack(side="left", padx=5)

        self.comment_sort_btn = ttk.Button(
            control_frame,
            text=" 🔄 評価点数順で並び替え ",
            command=self.sort_by_score,
            state="disabled",
        )
        self.comment_sort_btn.pack(side="left", padx=5)

        self.reset_sort_btn = ttk.Button(
            control_frame,
            text=" ⏪ 初期順に戻す ",
            command=self.reset_to_initial_order,
            state="disabled",
        )
        self.reset_sort_btn.pack(side="left", padx=5)

        self.sort_status_label = ttk.Label(
            control_frame, text="現在: 初期順", foreground="blue"
        )
        self.sort_status_label.pack(side="left", padx=8)

        self.ext_comment_btn = ttk.Button(
            control_frame,
            text=" 💬 外部コメントCSV読込 ",
            command=self.load_external_comment_csv,
            state="disabled",
        )
        self.ext_comment_btn.pack(side="left", padx=5)

        self.file_label = ttk.Label(
            control_frame, text="ファイルが選択されていません", foreground="gray"
        )
        self.file_label.pack(side="left", padx=10)

        # 出力ボタン群（右側に配置）
        self.html_btn = ttk.Button(
            control_frame,
            text=" 🌐 HTML出力 ",
            command=self.export_html,
            state="disabled",
        )
        self.html_btn.pack(side="right", padx=5)

        self.csv_btn = ttk.Button(
            control_frame,
            text=" 💾 CSV出力 ",
            command=self.export_csv,
            state="disabled",
        )
        self.csv_btn.pack(side="right", padx=5)

        # --- 開催場・レース切り替え（TARGET風） ---
        self.cell_font = ("Meiryo UI", 10)
        self.cell_font_bold = ("Meiryo UI", 10, "bold")

        nav_frame = ttk.LabelFrame(self, text=" 開催・レース選択 ", padding=6)
        nav_frame.pack(fill="x", padx=15, pady=2)

        self.venue_frame = tk.Frame(nav_frame)
        self.venue_frame.pack(fill="x")
        self.race_frame = tk.Frame(nav_frame)
        self.race_frame.pack(fill="x", pady=(4, 0))

        self.race_header_label = tk.Label(
            self,
            text="指数CSVファイルを読み込んでください",
            bg="#0a1128",
            fg="white",
            font=("Meiryo UI", 13, "bold"),
            anchor="w",
            padx=14,
            pady=8,
        )
        self.race_header_label.pack(fill="x", padx=15, pady=(6, 0))

        # --- 中央：一覧表示エリア（セル単位で色を付けられるグリッド） ---
        table_frame = ttk.LabelFrame(
            self, text=" 出走馬・指数分析一覧（指数順位カラー付き） ", padding=10
        )
        table_frame.pack(fill="both", expand=True, padx=15, pady=5)

        self.columns = (
            "レース",
            "条件",
            "枠番",
            "馬番",
            "推印",
            "馬名",
            "単勝オッズ",
            "KOLオッズ",
            "arms",
            "arms2",
            "TUA",
            "S指数",
            "F指数",
            "厩舎finish-up",
            "総合評価・コース相性判定",
        )
        headers_text = {
            "レース": "レース",
            "条件": "コース条件",
            "枠番": "枠番",
            "馬番": "馬番",
            "推印": "推印",
            "馬名": "馬名",
            "単勝オッズ": "単勝",
            "KOLオッズ": "KOL",
            "arms": "arms",
            "arms2": "arms2",
            "TUA": "TUA",
            "S指数": "S指数",
            "F指数": "F指数",
            "厩舎finish-up": "厩舎F-up",
            "総合評価・コース相性判定": "信頼度判定 ＆ 特注・コース相性コメント",
        }
        # 列幅（ピクセル）。ヘッダー行と表本体で同じ値を使い、列をそろえる
        self.col_widths = [55, 100, 40, 40, 40, 100, 60, 60, 50, 50, 50, 50, 50, 50, 645]

        # 指数の順位色（TARGET風）：1位=黄, 2位=水色, 3位=緑
        self.rank_colors = {1: "#ffff66", 2: "#99ddff", 3: "#99e699"}
        # 順位色を付ける列（キー -> self.columns内の列番号）
        self.rank_columns = {"arms": 8, "arms2": 9, "TUA": 10, "S": 11, "F": 12, "finish_up": 13}

        # ヘッダーは表本体と同じ grid_frame 内に描画する。
        # 別コンテナにするとTkinterが列幅を別々に計算するため、ズレの原因になる。
        self.header_frame = None

        body = tk.Frame(table_frame)
        body.pack(fill="both", expand=True)

        self.grid_canvas = tk.Canvas(
            body, highlightthickness=0, bg="white", height=300
        )
        # 縦スクロール
        v_scrollbar = ttk.Scrollbar(
            body, orient="vertical", command=self.grid_canvas.yview
        )

        # 横スクロール
        h_scrollbar = ttk.Scrollbar(
            body, orient="horizontal", command=self.grid_canvas.xview
        )

        self.grid_canvas.configure(
            yscrollcommand=v_scrollbar.set,
            xscrollcommand=h_scrollbar.set,
        )

        v_scrollbar.pack(side="right", fill="y")
        h_scrollbar.pack(side="bottom", fill="x")
        self.grid_canvas.pack(side="left", fill="both", expand=True)

        self.grid_frame = tk.Frame(self.grid_canvas, bg="white")
        self.grid_window = self.grid_canvas.create_window(
            (0, 0), window=self.grid_frame, anchor="nw"
        )
        self.grid_canvas.bind("<Configure>", self._fit_table_width)
        self.grid_frame.bind(
            "<Configure>",
            lambda e: self.grid_canvas.configure(
                scrollregion=self.grid_canvas.bbox("all")
            ),
        )
        self.bind_all("<MouseWheel>", self._on_mousewheel)
        self.bind_all("<Shift-MouseWheel>", self._on_shift_mousewheel)

        self.df_current = None
        self.export_data_list = []
        self.initial_data_list = []
        self.display_all = []  # 現在の並び順の全レース分データ
        self.view_rows = []  # 画面に表示中のレースのデータ
        self.row_cells = []
        self.row_base_bg = []
        self.selected_row = None
        self.sel_venue = None
        self.sel_race = None  # 数値 or "ALL"
        self.source_name = ""
        self.score_sort_descending = True  # デフォルトはスコア高い順

    def open_snapshot_creator(self):
        window = getattr(self, 'snapshot_window', None)
        if window is None or not window.winfo_exists():
            self.snapshot_window = SnapshotCreator(self, csv_path=self.__dict__.get('source_path', ''),
                                                   on_created=self._on_snapshot_created)
        self.snapshot_window.lift()

    def _on_snapshot_created(self, path, metadata):
        window = getattr(self, 'cushion_window', None)
        if window is not None and window.winfo_exists() and window.context:
            rows = window.context[0]
            if rows and rows[0].get('race_id', '')[:8] == metadata['target_date']:
                window.db_path = path
                window.refresh()

    def open_cushion_viewer(self):
        if not self.view_rows:
            messagebox.showinfo("クッション値別成績", "指数CSVを読み込み、芝のレース番号を選択してください。")
            return
        if self.cushion_window is None or not self.cushion_window.winfo_exists():
            self.cushion_window = CushionViewerWindow(self)
        self.cushion_window.sync(self.view_rows, self.sel_venue, self.sel_race, self.source_name)
        self.cushion_window.lift()

    def _sync_cushion_window(self):
        window = getattr(self, 'cushion_window', None)
        if window is not None and window.winfo_exists():
            window.sync(self.view_rows, self.sel_venue, self.sel_race, self.source_name)

    def load_course_data(self):
        self.course_stats = {}
        try:
            df = pd.read_csv("arms及びarms2及びTUA指数の全てが一位.csv", encoding="cp932")
            self.course_stats["triple"] = df
        except Exception as e:
            print(f"失敗: arms及びarms2及びTUA指数の全てが一位.csv: {e}")

        csv_files = glob.glob("*指数*位のコース別成績.csv")
        for filepath in csv_files:
            filename = os.path.basename(filepath)
            try:
                df = pd.read_csv(filename, encoding="cp932")
                self.course_stats[filename] = df
            except Exception as e:
                print(f"失敗: {filename}: {e}")

    def parse_racetrack(self, race_str):
        race_str = str(race_str).strip()
        if not race_str:
            return ""
        char = race_str[0]
        mapping = {
            "東": "東京",
            "中": "中山",
            "福": "福島",
            "京": "京都",
            "阪": "阪神",
            "新": "新潟",
            "札": "札幌",
            "函": "函館",
            "小": "小倉",
            "名": "中京",
        }
        return mapping.get(char, char)

    def get_course_compatibility(
        self, race_col, surface, distance, index_type, rank
    ):
        target_filename = f"{index_type}指数{rank}位のコース別成績.csv"
        df = None
        if target_filename in self.course_stats:
            df = self.course_stats[target_filename]

        if df is not None:
            track_name = self.parse_racetrack(race_col)
            for idx, row in df.iterrows():
                c_target = str(row.get("コース", ""))
                if track_name and track_name in c_target:
                    if surface in c_target and str(distance) in c_target:
                        return {
                            "course": c_target,
                            "win_rate": str(row.get("勝率", "0%")),
                            "place_rate": str(row.get("複勝率", "0%")),
                            "win_ret": str(row.get("単勝回収値", "0")),
                            "place_ret": str(row.get("複勝回収値", "0")),
                            "avg_rank": str(row.get("平均着順", "")),
                        }
        return None

    def load_csv(self):
        file_path = filedialog.askopenfilename(
            title="指数CSVファイルを選択",
            filetypes=[("CSV Files", "*.csv"), ("All Files", "*.*")],
        )
        if not file_path:
            return

        try:
            df = pd.read_csv(file_path, encoding="cp932", header=None, converters={15: str, 16: str, 17: str})
            self.file_label.config(
                text=f"読込ファイル: {os.path.basename(file_path)} (全 {len(df)} 頭)",
                foreground="black",
            )
            self.df_current = df
            self.source_name = os.path.basename(file_path)
            self.source_path = file_path
            self.sel_venue = None
            self.sel_race = None
            self.ext_comment_btn.config(state="normal")
            self.odds_btn.config(state="normal")
            self.comment_sort_btn.config(state="normal")
            self.reset_sort_btn.config(state="normal")
            self.process_and_display_data(df)

            self.csv_btn.config(state="normal")
            self.html_btn.config(state="normal")
            self.kol_html_btn.config(state="normal")
            self.sort_status_label.config(text="現在の状態: 初期読込順")
        except Exception as e:
            messagebox.showerror(
                "読み込みエラー", f"ファイルの読み込みに失敗しました。\n詳細: {e}"
            )


    def update_win_odds(self):
        """読み込み中CSVの日付と各行の開催場/R/馬番からTARGET単勝オッズを反映する。"""
        if not self.export_data_list:
            messagebox.showwarning("警告", "先に指数CSVファイルを読み込んでください。")
            return

        yyyymmdd = resolve_race_date(self.export_data_list, self.source_name)
        if not yyyymmdd:
            messagebox.showerror(
                "オッズ更新エラー",
                "CSVのレースIDから開催日を一意に取得できません。\n"
                "レースIDがない場合は、ファイル名をYYYYMMDD.csvにしてください。\n"
                "例: 20261003.csv（存在する日付の8桁）"
            )
            return

        rt_day = TARGET_ROOT / "RT_DATA" / yyyymmdd[:4] / yyyymmdd[4:8]
        if not rt_day.exists():
            messagebox.showerror(
                "オッズ更新エラー",
                f"TARGETのRT_DATAが見つかりません。\n{rt_day}"
            )
            return

        # 同一レースは一度だけファイルを読む
        race_cache = {}
        updated = 0
        missing_races = set()
        missing_horses = []

        for row in self.export_data_list:
            venue = row.get("venue", "")
            race_no = row.get("race_no", 0)
            race_id = (venue, race_no)

            if race_id not in race_cache:
                rt_file = find_target_rt_file(TARGET_ROOT, yyyymmdd, venue, race_no)
                if rt_file is None:
                    race_cache[race_id] = {}
                    missing_races.add(f"{venue}{race_no}R")
                else:
                    race_cache[race_id] = read_target_rt_win_data(rt_file)

            try:
                horse_no = int(float(str(row.get("馬番", "")).strip()))
            except (TypeError, ValueError):
                continue

            win_data = race_cache[race_id].get(horse_no)
            if win_data is not None:
                row["単勝オッズ"] = f"{win_data['odds']:.1f}"
                row["actual_popularity"] = win_data["popularity"]
                updated += 1
            else:
                row["単勝オッズ"] = ""
                row["actual_popularity"] = None
                if race_cache[race_id]:
                    missing_horses.append(f"{venue}{race_no}R {horse_no}番")

        # initial_data_list と同じdictを通常は共有しているが、
        # 念のため venue/race_no/馬番 で値を同期する。
        odds_map = {
            (r.get("venue"), r.get("race_no"), str(r.get("馬番"))):
                (r.get("単勝オッズ", ""), r.get("actual_popularity"))
            for r in self.export_data_list
        }
        for collection in (self.initial_data_list, self.display_all):
            for r in collection:
                k = (r.get("venue"), r.get("race_no"), str(r.get("馬番")))
                if k in odds_map:
                    r["単勝オッズ"], r["actual_popularity"] = odds_map[k]

        for collection in (self.export_data_list, self.initial_data_list, self.display_all):
            for row in collection:
                refresh_finish_up_comment(row)

        self.set_display_data(self.display_all or self.export_data_list)

        msg = f"単勝オッズを更新しました。\n{yyyymmdd} / {updated}頭"
        if missing_races:
            msg += "\n\nRTファイルを特定できなかったレース:\n" + ", ".join(sorted(missing_races))
        if missing_horses:
            preview = ", ".join(missing_horses[:10])
            msg += f"\n\nオッズ未取得: {len(missing_horses)}頭"
            if preview:
                msg += "\n" + preview
        messagebox.showinfo("オッズ更新", msg)

    def load_external_comment_csv(self):
        file_path = filedialog.askopenfilename(
            title="外部コメントCSVファイルを選択",
            filetypes=[("CSV Files", "*.csv"), ("All Files", "*.*")],
        )
        if not file_path:
            return

        try:
            df_ext = pd.read_csv(file_path, encoding="cp932", header=None)
            comment_dict = {}

            for _, row in df_ext.iterrows():
                vals = [str(v).strip() for v in row.values if pd.notna(v)]
                if len(vals) >= 6:
                    h_name = vals[2]  # 馬名
                    c_text = vals[5]  # コメント
                    if h_name and c_text:
                        comment_dict[h_name] = c_text

            self.ext_comment_df = comment_dict
            messagebox.showinfo(
                "成功",
                f"外部コメントを読み込みました（{len(comment_dict)}頭分）。\n自動でデータを更新します。",
            )

            if self.df_current is not None:
                self.process_and_display_data(self.df_current)

        except Exception as e:
            messagebox.showerror(
                "エラー", f"外部コメントCSVの読み込みに失敗しました。\n詳細: {e}"
            )

    def process_and_display_data(self, df):
        input_fields = normalize_main_frame(df)
        # 元の入力列数を、計算用列を追加する前に取得する。
        source_columns = {c for c in df.columns if isinstance(c, int)}
        df["arms_val"] = pd.to_numeric(df.iloc[:, 8], errors="coerce").fillna(0)
        df["arms2_val"] = pd.to_numeric(df.iloc[:, 9], errors="coerce").fillna(0)
        df["tua_val"] = pd.to_numeric(df.iloc[:, 10], errors="coerce").fillna(0)
        df["S_val"] = pd.to_numeric(df.iloc[:, 11], errors="coerce").fillna(0)
        df["F_val"] = pd.to_numeric(df.iloc[:, 12], errors="coerce").fillna(0)

        if 13 in source_columns:
            df["finish_up_val"] = pd.to_numeric(
                df.iloc[:, 13], errors="coerce"
            ).fillna(0)
        else:
            df["finish_up_val"] = 0

        # CSV 15列目（Pythonでは列番号14）をKOLオッズとして読み込む
        if 14 in source_columns:
            df["kol_odds_val"] = pd.to_numeric(
                df.iloc[:, 14], errors="coerce"
            )
        else:
            df["kol_odds_val"] = pd.NA

        temp_data_list = []
        df["race_group"] = df.apply(
            lambda r: f"{r.get(0, '')}_{r.get(1, '')}_{r.get(2, '')}_{r.get(3, '')}",
            axis=1,
        )

        df["arms_rank"] = df.groupby("race_group")["arms_val"].rank(
            ascending=False, method="min"
        )
        df["arms2_rank"] = df.groupby("race_group")["arms2_val"].rank(
            ascending=False, method="min"
        )
        df["tua_rank"] = df.groupby("race_group")["tua_val"].rank(
            ascending=False, method="min"
        )
        df["S_rank"] = df.groupby("race_group")["S_val"].rank(
            ascending=False, method="min"
        )
        df["F_rank"] = df.groupby("race_group")["F_val"].rank(
            ascending=False, method="min"
        )
        df["finish_up_rank"] = df.groupby("race_group")["finish_up_val"].rank(
            ascending=False, method="min"
        )

        df["finish_up_count"] = df.groupby(["race_group", "finish_up_val"])[
            "finish_up_val"
        ].transform("count")

        for idx, row in df.iterrows():
            race_raw = str(row.get(0, ""))
            cond_name = str(row.get(1, ""))
            surface = str(row.get(2, ""))

            dist_raw = row.get(3, 0)
            try:
                distance = int(dist_raw)
            except ValueError:
                distance = 0

            cond_raw = f"{cond_name} {surface}{distance}"
            header_text = f"{cond_name} {surface}{distance}m"
            venue_name = self.parse_racetrack(race_raw)
            race_m = re.match(r"^\D+?(\d+)$", race_raw.strip())
            race_no = int(race_m.group(1)) if race_m else 0
            wakuban_raw = row.get(4, "")
            wakuban = (
                int(wakuban_raw)
                if pd.notna(wakuban_raw) and str(wakuban_raw).isdigit()
                else 0
            )
            umaban = str(row.get(5, ""))
            push_mark = str(row.get(6, "")).strip()
            if push_mark.lower() == "nan":
                push_mark = ""

            name = str(row.get(7, "")).strip()

            arms = row["arms_val"]
            arms2 = row["arms2_val"]
            tua = row["tua_val"]
            s_idx = row["S_val"]
            f_idx = row["F_val"]
            finish_up = row["finish_up_val"]

            # KOLオッズ：CSV 15列目
            kol_raw = row.get("kol_odds_val", pd.NA)
            if pd.isna(kol_raw):
                kol_odds = ""
            else:
                kol_odds = f"{float(kol_raw):.1f}"

            arms_rank = int(row["arms_rank"])
            arms2_rank = int(row["arms2_rank"])
            tua_rank = int(row["tua_rank"])
            s_rank = int(row["S_rank"])
            f_rank = int(row["F_rank"])
            finish_up_rank = int(row["finish_up_rank"])
            finish_up_count = row["finish_up_count"]

            highlights = []
            score = 0

            if arms >= 110:
                highlights.append(f"arms:{arms}")
                score += 1
            if arms2 >= 120:
                highlights.append(f"arms2:{arms2}")
                score += 1

            if tua >= 220:
                highlights.append(f"TUA:{tua}(最強)")
                score += 2
            elif tua >= 200:
                highlights.append(f"TUA:{tua}(有力)")
                score += 1

            if s_idx >= 60:
                highlights.append(f"S:{s_idx}(最強)")
                score += 2
            elif s_idx >= 55:
                highlights.append(f"S:{s_idx}(有力)")
                score += 1

            if f_idx >= 70:
                highlights.append(f"F:{f_idx}(鉄板)")
                score += 2
            elif f_idx >= 65:
                highlights.append(f"F:{f_idx}(軸)")
                score += 1

            if finish_up_count < 4:
                if finish_up >= 5 or finish_up_rank <= 3:
                    highlights.append("調教良")
                    score += 1

            course_compat_text = ""
            is_good_compatibility = False
            is_triple_1st = False

            if arms_rank == 1 and arms2_rank == 1 and tua_rank == 1:
                if "triple" in self.course_stats:
                    df_triple = self.course_stats["triple"]
                    track_name = self.parse_racetrack(race_raw)
                    for _, t_row in df_triple.iterrows():
                        c_target = str(t_row.get("コース", ""))
                        if track_name and track_name in c_target:
                            if surface in c_target and str(distance) in c_target:
                                compat = {
                                    "course": c_target,
                                    "win_rate": str(t_row.get("勝率", "0%")),
                                    "place_rate": str(t_row.get("複勝率", "0%")),
                                    "win_ret": str(t_row.get("単勝回収値", "0")),
                                    "place_ret": str(t_row.get("複勝回収値", "0")),
                                }
                                try:
                                    win_ret_val = float(
                                        str(compat["win_ret"])
                                        .replace("%", "")
                                        .strip()
                                    )
                                except ValueError:
                                    win_ret_val = 0.0
                                try:
                                    place_rate_val = float(
                                        str(compat["place_rate"])
                                        .replace("%", "")
                                        .strip()
                                    )
                                except ValueError:
                                    place_rate_val = 0.0

                                if win_ret_val >= 100 or place_rate_val >= 60:
                                    is_triple_1st = True
                                    course_compat_text = f"👑 【★トリプル１位★: {compat['course']} 複勝率{compat['place_rate']}/単回{compat['win_ret']}】"
                                    score += 3
                                break

            if not is_triple_1st:
                checks = [
                    ("arms", arms_rank),
                    ("arms2", arms2_rank),
                    ("TUA", tua_rank),
                    ("S", s_rank),
                    ("F", f_rank),
                ]
                for t, rnk in checks:
                    if rnk <= 3:
                        compat = self.get_course_compatibility(
                            race_raw, surface, distance, t, rnk
                        )
                        if compat:
                            try:
                                win_ret_val = float(
                                    str(compat["win_ret"])
                                    .replace("%", "")
                                    .strip()
                                )
                            except ValueError:
                                win_ret_val = 0.0
                            try:
                                place_rate_val = float(
                                    str(compat["place_rate"])
                                    .replace("%", "")
                                    .strip()
                                )
                            except ValueError:
                                place_rate_val = 0.0

                            if win_ret_val >= 100 or place_rate_val >= 60:
                                is_good_compatibility = True
                                course_compat_text = f"🎯 【{t}{rnk}位: {compat['course']} 複勝率{compat['place_rate']}/単回{compat['win_ret']}】(好相性)"
                                score += 1
                                break

            is_dirt = surface == "ダ"
            is_not_maishin = "未勝利" not in cond_name and "新馬" not in cond_name
            is_outer_gate = wakuban in [6, 7, 8]
            is_s_top = s_rank == 1

            suna_食_text = ""
            if is_dirt and is_not_maishin and is_outer_gate and is_s_top:
                suna_食_text = "★特注砂食★"
                score += 1

            is_8_gate = wakuban == 8
            is_f72_over = f_idx >= 72
            is_not_1200 = distance != 1200

            f72_text = ""
            if is_dirt and is_8_gate and is_f72_over and is_not_1200:
                f72_text = "★特注F72★"
                score += 1

            track_name_parsed = self.parse_racetrack(race_raw)
            is_nakayama_turf_1600 = (
                track_name_parsed == "中山" and surface == "芝" and distance == 1600
            )
            is_gate_1_to_4 = wakuban in [1, 2, 3, 4]

            nakayama_1600_text = ""
            if is_nakayama_turf_1600 and is_gate_1_to_4 and s_rank == 1:
                nakayama_1600_text = "★中山芝1600特注★"
                score += 1

            is_nakayama_turf_2000 = (
                track_name_parsed == "中山" and surface == "芝" and distance == 2000
            )
            is_gate_1_to_4_or_8 = wakuban in [1, 2, 3, 4, 8]

            nakayama_2000_text = ""
            if is_nakayama_turf_2000 and is_gate_1_to_4_or_8 and f_rank == 1:
                nakayama_2000_text = "★中山芝2000特注★"
                score += 1

            eval_parts = []
            if nakayama_2000_text:
                eval_parts.append(nakayama_2000_text)
            if nakayama_1600_text:
                eval_parts.append(nakayama_1600_text)
            if suna_食_text:
                eval_parts.append(suna_食_text)
            if f72_text:
                eval_parts.append(f72_text)

            if highlights:
                eval_parts.extend(highlights)
            if course_compat_text:
                eval_parts.append(course_compat_text)

            row_tag = ""
            if not eval_parts:
                eval_text = ""
            else:
                eval_text = " / ".join(eval_parts)
                if is_triple_1st:
                    eval_text = "🌟 【★トリプル１位★推奨】 " + eval_text
                    row_tag = "triple1st"
                elif score >= 4:
                    eval_text = "🔥 【軸馬推奨】 " + eval_text
                    row_tag = "axis"
                elif score >= 2:
                    eval_text = "⭐ 【有力候補】 " + eval_text
                    row_tag = "candidate"
                elif (
                    is_good_compatibility
                    or suna_食_text
                    or f72_text
                    or nakayama_1600_text
                    or nakayama_2000_text
                ):
                    eval_text = "🎯 【注目条件】 " + eval_text
                    row_tag = "special"
                else:
                    row_tag = "special"

            # 外部コメントの結合（馬名が一致する場合）
            if self.ext_comment_df and name in self.ext_comment_df:
                ext_comment = self.ext_comment_df[name]
                if eval_text:
                    eval_text = f"{ext_comment} ▼ {eval_text}"
                else:
                    eval_text = ext_comment

            temp_data_list.append({
                "レース": race_raw,
                "条件": cond_raw,
                "枠番": wakuban,
                "馬番": umaban,
                "推印": push_mark,
                "馬名": name,
                "単勝オッズ": "",
                "KOLオッズ": kol_odds,
                "race_id": str(row.get(15, "")).strip() if pd.notna(row.get(15)) else "",
                "jockey": str(input_fields.loc[row.name, "jockey"]).strip() if pd.notna(input_fields.loc[row.name, "jockey"]) else "",
                "horse_id": str(input_fields.loc[row.name, "horse_id"]).strip() if pd.notna(input_fields.loc[row.name, "horse_id"]) else "",
                "surface": str(row.get(2, "")).strip(),
                "actual_popularity": None,
                "arms": arms,
                "arms2": arms2,
                "TUA": tua,
                "S指数": s_idx,
                "F指数": f_idx,
                "厩舎finish-up": finish_up,
                "総合評価・コース相性判定": eval_text,
                "base_comment": eval_text,
                "class_name": cond_name,
                "score": score,  # 評価点数（ソート用）
                "tag": row_tag,
                "venue": venue_name,
                "race_no": race_no,
                "header": header_text,
                "ranks": {
                    "arms": arms_rank,
                    "arms2": arms2_rank,
                    "TUA": tua_rank,
                    "S": s_rank,
                    "F": f_rank,
                    "finish_up": finish_up_rank,
                },
            })

        # 初期読込順を保持
        self.initial_data_list = list(temp_data_list)
        self.export_data_list = list(temp_data_list)
        self.set_display_data(self.export_data_list)

    def _on_mousewheel(self, event):
        if event.delta:
            self.grid_canvas.yview_scroll(-1 if event.delta > 0 else 1, "units")

    def _on_shift_mousewheel(self, event):
        """Shift + マウスホイールで表を横スクロールする。"""
        if event.delta:
            self.grid_canvas.xview_scroll(-1 if event.delta > 0 else 1, "units")

    def _venue_order(self):
        base = self.initial_data_list or self.display_all
        return list(dict.fromkeys(r["venue"] for r in base))

    def _race_numbers(self, venue):
        base = self.initial_data_list or self.display_all
        return sorted({r["race_no"] for r in base if r["venue"] == venue})

    def set_display_data(self, data_list):
        """並び順を保持して、開催場タブ・Rボタン・表を更新する。"""
        self.display_all = list(data_list)
        venues = self._venue_order()
        if not venues:
            return
        if self.sel_venue not in venues:
            self.sel_venue = venues[0]
            self.sel_race = None
        races = self._race_numbers(self.sel_venue)
        if self.sel_race != "ALL" and self.sel_race not in races:
            self.sel_race = races[0] if races else "ALL"
        self.build_nav()
        self.render_table()

    def _nav_button(self, parent, text, active, command, width):
        tk.Button(
            parent,
            text=text,
            command=command,
            width=width,
            bg="#1e90c8" if active else "#e3eaf1",
            fg="white" if active else "#222222",
            activebackground="#1e90c8",
            activeforeground="white",
            relief="flat",
            bd=0,
            font=self.cell_font_bold if active else self.cell_font,
            pady=3,
        ).pack(side="left", padx=2)

    def build_nav(self):
        for w in self.venue_frame.winfo_children():
            w.destroy()
        for w in self.race_frame.winfo_children():
            w.destroy()

        for v in self._venue_order():
            self._nav_button(
                self.venue_frame,
                v,
                v == self.sel_venue,
                lambda v=v: self.select_venue(v),
                8,
            )
        for n in self._race_numbers(self.sel_venue):
            self._nav_button(
                self.race_frame,
                f"{n}R",
                n == self.sel_race,
                lambda n=n: self.select_race(n),
                5,
            )
        self._nav_button(
            self.race_frame,
            "全R",
            self.sel_race == "ALL",
            lambda: self.select_race("ALL"),
            5,
        )

    def select_venue(self, venue):
        self.sel_venue = venue
        races = self._race_numbers(venue)
        self.sel_race = races[0] if races else "ALL"
        self.build_nav()
        self.render_table()

    def select_race(self, race):
        self.sel_race = race
        self.build_nav()
        self.render_table()

    def render_table(self):
        """選択中の開催場・レースの馬だけを、セル単位の色付きで表示する。"""
        for w in self.grid_frame.winfo_children():
            w.destroy()
        self.row_cells = []
        self.row_base_bg = []
        self.selected_row = None

        if self.sel_race == "ALL":
            rows = [r for r in self.display_all if r["venue"] == self.sel_venue]
            title = f"{self.sel_venue}　全レース"
        else:
            rows = [
                r
                for r in self.display_all
                if r["venue"] == self.sel_venue and r["race_no"] == self.sel_race
            ]
            head = rows[0]["header"] if rows else ""
            title = f"{self.sel_venue}　{self.sel_race}R　{head}"
        self.view_rows = rows
        self._sync_cushion_window()

        race_date = resolve_race_date(self.display_all, self.source_name)
        date_text = (
            f"{race_date[:4]}/{race_date[4:6]}/{race_date[6:8]}"
            if race_date
            else ""
        )
        self.race_header_label.config(
            text=f"{title}　　{date_text}　{len(rows)}頭"
        )

        for c in range(len(self.columns)):
            self.grid_frame.grid_columnconfigure(
                c, minsize=self.col_widths[c], weight=0
            )

        # ヘッダーとデータを同じGridに置くことで、列境界を完全に共有する。
        headers_text = {
            "レース": "レース",
            "条件": "コース条件",
            "枠番": "枠番",
            "馬番": "馬番",
            "推印": "推印",
            "馬名": "馬名",
            "単勝オッズ": "単勝",
            "KOLオッズ": "KOL",
            "arms": "arms",
            "arms2": "arms2",
            "TUA": "TUA",
            "S指数": "S指数",
            "F指数": "F指数",
            "厩舎finish-up": "厩舎F-up",
            "総合評価・コース相性判定": "信頼度判定 ＆ 特注・コース相性コメント",
        }
        for c, col in enumerate(self.columns):
            tk.Label(
                self.grid_frame,
                text=headers_text[col],
                bg="#3498db",
                fg="white",
                font=self.cell_font_bold,
                width=1,
                relief="ridge",
                bd=1,
                pady=3,
            ).grid(row=0, column=c, sticky="nsew")

        comment_col = "総合評価・コース相性判定"
        for r, row in enumerate(rows, start=1):
            labels = []
            bases = []
            _, kol_highlight = kol_gap_analysis(row, self.qualified_jockeys)
            for c, col in enumerate(self.columns):
                bg = "white"
                fg = "black"
                for key, col_idx in self.rank_columns.items():
                    if col_idx == c:
                        bg = self.rank_colors.get(row["ranks"][key], "white")
                if col == "KOLオッズ" and kol_highlight:
                    bg = KOL_HIGHLIGHT_COLOR
                if col == "枠番":
                    bg, fg = wakuban_cell_colors(row[col], self.wakuban_colors)
                lbl = tk.Label(
                    self.grid_frame,
                    text=str(row[col]),
                    bg=bg,
                    fg=fg,
                    font=self.cell_font,
                    width=1,
                    anchor="w" if col in ("馬名", comment_col) else "center",
                    justify="left",
                    relief="ridge",
                    bd=1,
                    padx=3,
                    pady=2,
                    wraplength=(self.col_widths[c] - 10) if col == comment_col else 0,
                )
                lbl.grid(row=r, column=c, sticky="nsew")
                lbl.bind("<Button-1>", lambda e, i=r-1: self.select_row(i))
                labels.append(lbl)
                bases.append(bg)
            self.row_cells.append(labels)
            self.row_base_bg.append(bases)

        # 実際のフォント寸法から必要幅を計算するため、表示倍率にも追従する。
        regular = tkfont.Font(self, font=self.cell_font)
        bold = tkfont.Font(self, font=self.cell_font_bold)
        self.table_min_widths = []
        for c, col in enumerate(self.columns[:-1]):
            content_width = max((regular.measure(str(row[col])) for row in rows), default=0)
            self.table_min_widths.append(max(bold.measure(headers_text[col]), content_width) + 12)
        self.comment_min_width = max(220, regular.measure("あ" * 14) + 12)
        self._fit_table_width()

        self.grid_canvas.yview_moveto(0)

    def _fit_table_width(self, event=None):
        """コメント列に残り幅を割り当て、表全体をCanvasに合わせる。"""
        if not hasattr(self, "table_min_widths"):
            return
        available = event.width if event is not None else self.grid_canvas.winfo_width()
        fixed_width = sum(self.table_min_widths)
        comment_width = max(self.comment_min_width, available - fixed_width)
        self.col_widths = self.table_min_widths + [comment_width]
        for c, width in enumerate(self.col_widths):
            self.grid_frame.grid_columnconfigure(c, minsize=width, weight=0)
        self.grid_canvas.itemconfigure(self.grid_window, width=sum(self.col_widths))
        for label in self.grid_frame.grid_slaves(column=len(self.columns) - 1):
            label.configure(wraplength=comment_width - 10)
        if sum(self.col_widths) <= available:
            self.grid_canvas.xview_moveto(0)

    def _paint_row(self, idx, selected):
        for c, lbl in enumerate(self.row_cells[idx]):
            base = self.row_base_bg[idx][c]
            # 枠番・順位・KOLの色付きセルは維持し、白いセルだけ選択色にする
            lbl.config(bg="#cfe3ff" if (selected and base == "white") else base)

    def select_row(self, idx):
        if not (0 <= idx < len(self.view_rows)):
            return
        if self.selected_row is not None and self.selected_row < len(self.row_cells):
            self._paint_row(self.selected_row, False)
        self.selected_row = idx
        self._paint_row(idx, True)

    def sort_by_score(self):
        if not self.export_data_list:
            return

        self.score_sort_descending = True

        sorted_data = sorted(
            self.export_data_list,
            key=lambda x: x["score"],
            reverse=self.score_sort_descending,
        )
        self.set_display_data(sorted_data)

        self.sort_status_label.config(
            text="現在の状態: 評価点数順 [高得点順 (高->低)]", foreground="green"
        )

    def reset_to_initial_order(self):
        if not self.initial_data_list:
            return

        self.export_data_list = list(self.initial_data_list)
        self.set_display_data(self.export_data_list)

        self.score_sort_descending = True
        self.sort_status_label.config(
            text="現在の状態: 初期読込順に復帰しました", foreground="blue"
        )

    def export_csv(self):
        if not self.export_data_list:
            messagebox.showwarning("警告", "エクスポートするデータがありません。")
            return

        file_path = filedialog.asksaveasfilename(
            defaultextension=".csv",
            filetypes=[("CSV Files", "*.csv"), ("All Files", "*.csv")],
            title="CSVファイルとして保存",
        )
        if not file_path:
            return

        try:
            current_items = [
                {c: row[c] for c in self.columns} for row in self.display_all
            ]

            export_df = pd.DataFrame(current_items)

            if "総合評価・コース相性判定" in export_df.columns:
                export_df["総合評価・コース相性判定"] = export_df[
                    "総合評価・コース相性判定"
                ].apply(clean_text_for_target)

            export_df.to_csv(
                file_path, index=False, encoding="cp932", errors="ignore", header=False
            )
            messagebox.showinfo(
                "成功", f"TARGET用CSVファイルの保存が完了しました。\n{file_path}"
            )
        except Exception as e:
            messagebox.showerror("エラー", f"CSVの保存に失敗しました。\n詳細: {e}")

    def export_kol_html(self):
        self.export_html(kol_only=True)

    def export_html(self, kol_only=False):
        if not self.export_data_list:
            messagebox.showwarning("警告", "エクスポートするデータがありません。")
            return

        # 表示中の開催・レースだけでなく、読込済み全レースから抽出する。
        current_items = list(self.display_all)
        if kol_only:
            current_items = [
                row for row in current_items
                if kol_gap_analysis(row, self.qualified_jockeys)[1]
            ]
            if not current_items:
                messagebox.showinfo(
                    "KOL該当馬HTML出力",
                    "KOL色付け条件に該当する馬がいません。\n単勝オッズが未取得の場合は、先にオッズ更新を行ってください。",
                )
                return

        file_path = filedialog.asksaveasfilename(
            defaultextension=".html",
            filetypes=[("HTML Files", "*.html"), ("All Files", "*.*")],
            title="KOL該当馬をHTMLとして保存" if kol_only else "HTMLファイルとして保存",
        )
        if not file_path:
            return

        try:
            html_content = """<!DOCTYPE html>
<html lang="ja">
<head>
<meta charset="UTF-8">
<title>競馬指数 総合分析レポート</title>
<style>
    body { font-family: 'Helvetica Neue', Arial, sans-serif; margin: 20px; background-color: #f9f9f9; color: #333; }
    h2 { color: #2c3e50; border-bottom: 2px solid #3498db; padding-bottom: 5px; }
    table { width: 100%; border-collapse: collapse; margin-top: 15px; background-color: #fff; box-shadow: 0 2px 5px rgba(0,0,0,0.1); }
    th, td { border: 1px solid #ddd; padding: 10px; text-align: center; font-size: 14px; }
    th { background-color: #3498db; color: white; }
    td.name { text-align: left; }
    td.eval { text-align: left; font-weight: bold; }
    td.r1 { background-color: #ffff66; font-weight: bold; }
    td.r2 { background-color: #99ddff; font-weight: bold; }
    td.r3 { background-color: #99e699; font-weight: bold; }
    tr:hover { background-color: #f1f1f1; }
</style>
</head>
<body>
<h2>競馬指数 総合分析レポート</h2>
<table>
<thead>
<tr>
    <th>レース</th>
    <th>コース条件</th>
    <th>枠番</th>
    <th>馬番</th>
    <th>推印</th>
    <th>馬名</th>
    <th>単勝オッズ</th>
    <th>KOLオッズ</th>
    <th>arms</th>
    <th>arms2</th>
    <th>TUA</th>
    <th>S指数</th>
    <th>F指数</th>
    <th>厩舎finish-up</th>
    <th>総合評価・コース相性判定</th>
</tr>
</thead>
<tbody>
"""
            if kol_only:
                html_content = html_content.replace(
                    "競馬指数 総合分析レポート", "競馬指数 KOL該当馬レポート"
                )
            def rank_cls(row, key):
                r = row["ranks"][key]
                return f' class="r{r}"' if r in (1, 2, 3) else ""

            for row in current_items:
                html_content += "<tr>\n"
                html_content += f'  <td>{row["レース"]}</td>\n'
                html_content += f'  <td>{row["条件"]}</td>\n'
                gate_bg, gate_fg = wakuban_cell_colors(row["枠番"], self.wakuban_colors)
                html_content += f'  <td style="background-color:{gate_bg};color:{gate_fg}">{row["枠番"]}</td>\n'
                html_content += f'  <td>{row["馬番"]}</td>\n'
                html_content += f'  <td>{row["推印"]}</td>\n'
                html_content += f'  <td class="name">{row["馬名"]}</td>\n'
                html_content += f'  <td>{row["単勝オッズ"]}</td>\n'
                kol_style = (
                    f' style="background-color:{KOL_HIGHLIGHT_COLOR}"'
                    if kol_gap_analysis(row, self.qualified_jockeys)[1] else ""
                )
                html_content += f'  <td{kol_style}>{row.get("KOLオッズ", "")}</td>\n'
                html_content += (
                    f'  <td{rank_cls(row, "arms")}>{row["arms"]}</td>\n'
                )
                html_content += (
                    f'  <td{rank_cls(row, "arms2")}>{row["arms2"]}</td>\n'
                )
                html_content += (
                    f'  <td{rank_cls(row, "TUA")}>{row["TUA"]}</td>\n'
                )
                html_content += (
                    f'  <td{rank_cls(row, "S")}>{row["S指数"]}</td>\n'
                )
                html_content += (
                    f'  <td{rank_cls(row, "F")}>{row["F指数"]}</td>\n'
                )
                html_content += f'  <td{rank_cls(row, "finish_up")}>{row["厩舎finish-up"]}</td>\n'
                html_content += (
                    f'  <td class="eval">{row["総合評価・コース相性判定"]}</td>\n'
                )
                html_content += f"</tr>\n"

            html_content += """</tbody>
</table>
</body>
</html>
"""
            with open(file_path, "w", encoding="utf-8") as f:
                f.write(html_content)

            messagebox.showinfo(
                "成功", f"HTMLファイルの保存が完了しました。\n{file_path}"
            )
        except Exception as e:
            messagebox.showerror("エラー", f"HTMLの保存に失敗しました。\n詳細: {e}")

if __name__ == "__main__":
    app = HorseApp()
    app.mainloop()
