"""Reusable Tkinter panel. Embed after inspecting the actual Desktop app."""
from tkinter import ttk

from jra_cushion import fetch_jra_cushion
from cushion_presentation import METRICS, build_viewer_records
from cushion_stats import BAND_LABELS, cushion_band, get_cushion_stats, normalize_horse_id


class CushionStatsPanel(ttk.Frame):
    def __init__(self, parent, **kwargs):
        super().__init__(parent, **kwargs)
        self.heading = ttk.Label(self, text='クッション値別 過去成績')
        self.heading.pack(anchor='w')
        self.detail = ttk.Label(self, text='')
        self.detail.pack(anchor='w')
        container = ttk.Frame(self)
        container.pack(fill='both', expand=True)
        columns = ['馬番', '馬名', '着別度数', *METRICS, '対象走数', '中止', '失格', '備考']
        self.table = ttk.Treeview(container, columns=columns, show='headings')
        for column in columns:
            self.table.heading(column, text=column, command=lambda name=column: self.sort(name))
            self.table.column(column, width=240 if column == '備考' else (150 if column == '馬名' else 100),
                              minwidth=70, stretch=False, anchor='w' if column in {'馬名', '着別度数', '備考'} else 'e')
        vertical = ttk.Scrollbar(container, orient='vertical', command=self.table.yview)
        horizontal = ttk.Scrollbar(container, orient='horizontal', command=self.table.xview)
        self.table.configure(yscrollcommand=vertical.set, xscrollcommand=horizontal.set)
        self.table.grid(row=0, column=0, sticky='nsew')
        vertical.grid(row=0, column=1, sticky='ns')
        horizontal.grid(row=1, column=0, sticky='ew')
        container.rowconfigure(0, weight=1)
        container.columnconfigure(0, weight=1)
        self.records = []
        self.descending = {}

    def load(self, snapshot_path, entrants, race_date, cushion_value, *, venue='', race_no='', surface='芝', official_only=False):
        self.descending = {}
        if surface != '芝':
            self.heading.config(text='ダートレースは芝クッション値別成績の対象外です。')
            self.detail.config(text='')
            self.records = []
        else:
            horse_ids = []
            for horse in entrants:
                try:
                    horse_ids.append(normalize_horse_id(horse.get('horse_id', '')))
                except ValueError:
                    pass
            report = get_cushion_stats(snapshot_path, horse_ids,
                                      race_date, cushion_value, official_only=official_only)
            band = BAND_LABELS[cushion_band(cushion_value) - 1] if cushion_value is not None else '未取得'
            self.heading.config(text=f'{race_date} {venue}{race_no}R ／ クッション値：{cushion_value if cushion_value is not None else "未取得"} ／ 区分：{band}')
            metadata = report['metadata']
            self.detail.config(text=f"過去DB収録期間：{metadata.get('source_first_date', '')}～{metadata.get('source_last_date', '')} ／ {race_date}より前の芝・同区分のみ")
            self.records = build_viewer_records(entrants, report)
        self._draw()

    def load_jra(self, snapshot_path, entrants, race_date, *, venue, race_no='', surface='芝', official_only=False):
        if surface != '芝':
            self.load(snapshot_path, entrants, race_date, None, venue=venue, race_no=race_no, surface=surface)
            return None
        try:
            fetched = fetch_jra_cushion(race_date, venue)
        except Exception:
            # Clear previous results before the caller displays a retrieval error.
            self.load(snapshot_path, entrants, race_date, None, venue=venue, race_no=race_no, official_only=official_only)
            raise
        self.load(snapshot_path, entrants, race_date, fetched['value'], venue=venue, race_no=race_no, official_only=official_only)
        if fetched['value'] is None:
            self.heading.config(text=fetched['message'])
        return fetched

    def sort(self, column):
        descending = self.descending.get(column, column != '馬番')
        values = [r for r in self.records if r[column] is not None]
        missing = [r for r in self.records if r[column] is None]
        values.sort(key=lambda r: r['馬番'])
        values.sort(key=lambda r: r[column], reverse=descending)
        self.records = values + missing
        self.descending[column] = not descending
        self._draw()

    def _draw(self):
        self.table.delete(*self.table.get_children())
        for row in self.records:
            values = [f'{value:.1f}' if column in METRICS and value is not None else ('—' if value is None else value)
                      for column, value in row.items()]
            self.table.insert('', 'end', values=values)
