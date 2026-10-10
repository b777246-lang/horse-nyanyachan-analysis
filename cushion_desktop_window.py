"""Desktop viewer dialog; network work never touches Tk widgets."""
from pathlib import Path
from queue import Empty, Queue
from threading import Thread
import tkinter as tk
from tkinter import filedialog, ttk

from cushion_desktop import CushionStatsPanel
from cushion_presentation import build_viewer_records
from cushion_stats import cushion_band, normalize_date
from jra_cushion import fetch_jra_cushion


class CushionViewerWindow(tk.Toplevel):
    def __init__(self, parent):
        super().__init__(parent)
        self.title('クッション値別 過去成績')
        self.geometry('1150x520')
        self.context = None
        self.generation = 0
        self.results = Queue()
        self.manual_values = {}
        self.db_path = ''
        self.mode = tk.StringVar(value='JRA自動取得')
        self.value = tk.StringVar()
        self.official = tk.BooleanVar(value=False)
        controls = ttk.Frame(self, padding=8)
        controls.pack(fill='x')
        ttk.Button(controls, text='軽量DBを選択', command=self.choose_db).pack(side='left')
        self.db_label = ttk.Label(controls, text='軽量DB未選択')
        self.db_label.pack(side='left', padx=8)
        options = ttk.Frame(self, padding=8)
        options.pack(fill='x')
        for label in ('JRA自動取得', '手動入力'):
            ttk.Radiobutton(options, text=label, variable=self.mode, value=label, command=self.refresh).pack(side='left')
        ttk.Label(options, text='当日値：').pack(side='left', padx=(12, 0))
        self.entry = ttk.Entry(options, textvariable=self.value, width=8)
        self.entry.pack(side='left')
        self.entry.bind('<Return>', lambda event: self.refresh())
        ttk.Button(options, text='再取得／表示更新', command=self.refresh).pack(side='left', padx=8)
        ttk.Checkbutton(options, text='JRA公式照合済みのみ', variable=self.official, command=self.refresh).pack(side='left')
        self.status = ttk.Label(self, text='芝のレース番号を選択してください。', wraplength=1100, padding=8)
        self.status.pack(fill='x')
        self.panel = CushionStatsPanel(self)
        self.panel.pack(fill='both', expand=True, padx=8, pady=8)
        # Prevent the main app's bind_all wheel handlers from moving its table.
        self.bind('<MouseWheel>', lambda event: 'break')
        self.bind('<Shift-MouseWheel>', self._horizontal_wheel)
        self.poll_id = self.after(100, self._poll)

    def _horizontal_wheel(self, event):
        if event.delta:
            self.panel.table.xview_scroll(-1 if event.delta > 0 else 1, 'units')
        return 'break'

    def destroy(self):
        self.generation += 1
        if getattr(self, 'poll_id', None) is not None:
            self.after_cancel(self.poll_id)
        super().destroy()

    def sync(self, rows, venue, race_no, source_name):
        # Ignore score/order changes; the viewer always starts in horse-number order.
        ordered = sorted(rows, key=lambda row: int(row['馬番']))
        context = (ordered, venue, race_no)
        if context == self.context:
            return
        if self.context:
            old_rows, old_venue, _ = self.context
            if old_rows:
                self.manual_values[(old_rows[0]['race_id'][:8], old_venue)] = self.value.get()
        self.context = context
        day = ordered[0]['race_id'][:8] if ordered else ''
        self.value.set(self.manual_values.get((day, venue), ''))
        candidate = Path(__file__).parent / f'cushion_history_{day}.sqlite'
        if not self.db_path or (Path(self.db_path).name.startswith('cushion_history_') and candidate.is_file()):
            self.db_path = str(candidate) if candidate.is_file() else self.db_path
        self.refresh()

    def choose_db(self):
        path = filedialog.askopenfilename(parent=self, title='生成した軽量SQLiteを選択', filetypes=[('SQLite', '*.sqlite *.sqlite3 *.db')])
        if path:
            self.db_path = path
            self.refresh()

    def _placeholder(self, reason):
        rows = self.context[0] if self.context else []
        entrants = [{'horse_no': row['馬番'], 'horse_name': row['馬名'], 'horse_id': row.get('horse_id', '')} for row in rows]
        self.panel.records = build_viewer_records(entrants, unavailable_reason=reason)
        self.panel.heading.config(text='クッション値別 過去成績')
        self.panel.detail.config(text='')
        self.panel._draw()

    def refresh(self):
        self.generation += 1
        token = self.generation
        if not self.context:
            return
        rows, venue, race_no = self.context
        self.entry.config(state='normal' if self.mode.get() == '手動入力' else 'disabled')
        self.db_label.config(text=Path(self.db_path).name if self.db_path else '軽量DB未選択')
        self._placeholder('当日のクッション値未取得')
        if not rows or race_no == 'ALL':
            self.status.config(text='芝のレース番号を選択してください。全Rでは表示しません。')
            self.panel.records = []
            self.panel._draw()
            return
        if any(row.get('surface') != '芝' for row in rows):
            self.status.config(text='ダートレースは芝クッション値別成績の対象外です。')
            self.panel.records = []
            self.panel._draw()
            return
        try:
            dates = {normalize_date(row['race_id'][:8]) for row in rows}
            if len(dates) != 1:
                raise ValueError('開催日を一意に確認できません')
            day = dates.pop()
            if self.mode.get() == '手動入力':
                value = self.value.get().strip() or None
                if value is not None:
                    cushion_band(value)
                self.manual_values[(day, venue)] = self.value.get()
                self._display(value, '手動入力' if value is not None else '当日の公表値を入力してください。')
            else:
                self.status.config(text='JRAの当日クッション値を取得しています…')
                queue = self.results
                def worker():
                    try:
                        result = fetch_jra_cushion(day, venue)
                        queue.put((token, result, None))
                    except Exception as exc:
                        queue.put((token, None, str(exc)))
                Thread(target=worker, daemon=True).start()
        except (ValueError, KeyError) as exc:
            self.status.config(text=str(exc))

    def _poll(self):
        try:
            while True:
                token, result, error = self.results.get_nowait()
                if token != self.generation:
                    continue  # Result belongs to a previous race or input mode.
                if error:
                    self.status.config(text=f'JRA取得失敗：{error}。再取得または手動入力をご利用ください。')
                else:
                    note = result['message'] or f"JRA測定日時：{result['measurement_text']} ／ {result['year_basis']}"
                    self._display(result['value'], note)
        except Empty:
            pass
        self.poll_id = self.after(100, self._poll)

    def _display(self, value, note):
        rows, venue, race_no = self.context
        self.status.config(text=note)
        if not self.db_path:
            self._placeholder('軽量DB未選択')
            self.status.config(text=note + ' ／ 前日に生成した軽量DBを選択してください。')
            return
        entrants = [{'horse_no': row['馬番'], 'horse_name': row['馬名'], 'horse_id': row.get('horse_id', '')} for row in rows]
        try:
            self.panel.load(self.db_path, entrants, rows[0]['race_id'][:8], value,
                            venue=venue, race_no=race_no, official_only=self.official.get())
        except Exception as exc:
            self._placeholder('軽量DBを利用できません')
            self.status.config(text=f'軽量DBを利用できません：{exc}')
