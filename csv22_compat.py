"""Keep optional column 22 outside the pinned CSV21 research contract."""
import csv,io
def csv21_bytes(raw):
    rows=list(csv.reader(io.StringIO(raw.decode('cp932'),newline=''),strict=True))
    if rows and all(len(r)==21 for r in rows):return raw
    if not rows or not all(len(r)==22 for r in rows):return raw
    out=io.StringIO(newline='');csv.writer(out,lineterminator='\r\n').writerows(r[:21] for r in rows)
    return out.getvalue().encode('cp932')
