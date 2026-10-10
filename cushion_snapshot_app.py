"""Lightweight DB creation dialog, also runnable as a standalone Tkinter app."""
from pathlib import Path
from queue import Empty, Queue
from threading import Thread
import tkinter as tk
from tkinter import filedialog, ttk

from cushion_snapshot import create_snapshot, read_entrants


class SnapshotCreator(tk.Toplevel):
    def __init__(self, parent, *, csv_path='', on_created=None):
        super().__init__(parent)
        self.title('クッション値履歴の軽量DBを作成')
        self.geometry('850x330')
        self.on_created = on_created
        self.results = Queue()
        self.running = False
        self.source = tk.StringVar()
        self.csv = tk.StringVar(value=csv_path)
        self.output = tk.StringVar()
        self.status = tk.StringVar(value='元DBと対象日の出馬表CSVを選択してください。元DBは変更しません。')
        container = ttk.Frame(self, padding=12)
        container.pack(fill='both', expand=True)
        container.columnconfigure(1, weight=1)
        for row, (label, variable, command) in enumerate([
            ('元の競馬DB', self.source, self.choose_source),
            ('出馬表CSV（全レース）', self.csv, self.choose_csv),
            ('軽量DBの保存先', self.output, self.choose_output),
        ]):
            ttk.Label(container, text=label).grid(row=row, column=0, sticky='w', pady=6)
            ttk.Entry(container, textvariable=variable).grid(row=row, column=1, sticky='ew', padx=8)
            ttk.Button(container, text='選択', command=command).grid(row=row, column=2)
        self.create_button = ttk.Button(container, text='軽量DBを作成', command=self.start)
        self.create_button.grid(row=3, column=0, columnspan=3, pady=10)
        self.progress = ttk.Progressbar(container, mode='indeterminate')
        self.progress.grid(row=4, column=0, columnspan=3, sticky='ew')
        ttk.Label(container, textvariable=self.status, wraplength=800).grid(row=5, column=0, columnspan=3, sticky='w', pady=10)
        self._suggest_output()
        self.poll_id = self.after(100, self._poll)

    def choose_source(self):
        path = filedialog.askopenfilename(parent=self, title='元の競馬DBを選択', filetypes=[('SQLite', '*.db *.sqlite *.sqlite3')])
        if path:
            self.source.set(path)

    def choose_csv(self):
        path = filedialog.askopenfilename(parent=self, title='対象日の全レース出馬表CSVを選択', filetypes=[('CSV', '*.csv')])
        if path:
            self.csv.set(path)
            self._suggest_output()

    def _suggest_output(self):
        if not self.csv.get():
            return
        try:
            ids, day = read_entrants(self.csv.get())
            self.output.set(str(Path(self.csv.get()).parent / f'cushion_history_{day}.sqlite'))
            self.status.set(f'対象日：{day} ／ 出走馬：{len(ids)}頭。全レースをまとめて抽出します。')
        except (ValueError, OSError) as exc:
            self.status.set(f'出馬表CSVを確認してください：{exc}')

    def choose_output(self):
        path = filedialog.asksaveasfilename(parent=self, title='新しい軽量DBの保存先',
                                          initialfile=Path(self.output.get()).name or 'cushion_history.sqlite',
                                          defaultextension='.sqlite', filetypes=[('SQLite', '*.sqlite')], confirmoverwrite=False)
        if path:
            self.output.set(path)

    def start(self):
        if self.running:
            return
        source, csv_path, output = self.source.get().strip(), self.csv.get().strip(), self.output.get().strip()
        try:
            if not source or not csv_path or not output:
                raise ValueError('元DB・出馬表CSV・保存先の3項目を指定してください。')
            if not Path(source).is_file():
                raise ValueError('元DBが見つかりません。')
            if Path(output).exists():
                raise ValueError('保存先に同名ファイルがあります。新しい名前または別の保存先を指定してください。')
            ids, day = read_entrants(csv_path)
        except (ValueError, OSError) as exc:
            self.status.set(str(exc))
            return
        self.running = True
        self.create_button.config(state='disabled')
        self.progress.start(15)
        self.status.set(f'{day}・{len(ids)}頭の過去走を抽出しています…')
        queue = self.results
        def worker():
            try:
                metadata = create_snapshot(source, output, ids, day)
                queue.put((output, metadata, None))
            except Exception as exc:
                queue.put((output, None, str(exc)))
        Thread(target=worker, daemon=True).start()

    def _poll(self):
        try:
            output, metadata, error = self.results.get_nowait()
        except Empty:
            pass
        else:
            self.running = False
            self.progress.stop()
            self.create_button.config(state='normal')
            if error:
                self.status.set(f'作成に失敗しました：{error}')
            else:
                self.status.set(f"作成完了：{output}\n対象日：{metadata['target_date']} ／ {metadata['requested_horses']}頭・過去{metadata['history_rows']}走 ／ 元DB最終日：{metadata['source_last_date']} ／ クッション値異常：{metadata['cushion_anomalies']}件")
                if self.on_created:
                    self.on_created(output, metadata)
        self.poll_id = self.after(100, self._poll)

    def destroy(self):
        if getattr(self, 'poll_id', None) is not None:
            self.after_cancel(self.poll_id)
        super().destroy()


def main():
    root = tk.Tk()
    root.withdraw()
    window = SnapshotCreator(root)
    window.protocol('WM_DELETE_WINDOW', root.destroy)
    root.mainloop()


if __name__ == '__main__':
    main()
