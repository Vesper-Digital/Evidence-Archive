#!/usr/bin/env python3
"""Reads the DSX spreadsheets in /Tables and writes tables.json for the site.

Drop an .xlsx or .csv into a top-level `Tables` folder. This pulls the heading
block out of the sheet, keeps the first rows for the on-page preview, and
records the file so the page can offer it for download.

Nothing here is invented: every value comes from the sheet itself.
"""

import csv
import json
import os
import re

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TABLES = os.path.join(ROOT, "Tables")
GALLERY = os.path.join(ROOT, "Gallery")
OUT = os.path.join(ROOT, "assets", "tables.json")
GOUT = os.path.join(ROOT, "assets", "gallery.json")
LOGOS = os.path.join(ROOT, "assets", "tablelogos")

PREVIEW_ROWS = 14      # rows of data kept for the small preview
PREVIEW_COLS = 6


def human_size(n):
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024 or unit == "GB":
            return f"{n:.0f} {unit}" if unit == "B" else f"{n:,.0f} {unit}"
        n /= 1024.0


def clean(v):
    if v is None:
        return ""
    s = str(v).strip()
    s = s.replace("▶", "").replace("  ", " ")
    return re.sub(r"\s+", " ", s).strip()


def year_from(text):
    m = re.search(r"(19|20)\d{2}", text or "")
    return m.group(0) if m else ""


def save_logo(path, stem):
    """Pull the sheet's own logo out of the workbook so the page can show it.

    An .xlsx is a zip; its pictures live in xl/media. Reading them there works
    the same on every openpyxl version.
    """
    import zipfile
    try:
        with zipfile.ZipFile(path) as z:
            media = [n for n in z.namelist()
                     if n.startswith("xl/media/")
                     and n.lower().endswith((".png", ".jpg", ".jpeg", ".gif"))]
            if not media:
                print("    no logo found in the workbook")
                return ""
            media.sort()
            pick = media[0]
            data = z.read(pick)
    except Exception as e:                            # noqa: BLE001
        print(f"    could not read the logo: {e}")
        return ""

    ext = os.path.splitext(pick)[1].lower().lstrip(".")
    if ext == "jpeg":
        ext = "jpg"
    os.makedirs(LOGOS, exist_ok=True)
    name = re.sub(r"[^A-Za-z0-9._-]+", "-", stem).strip("-") + "." + ext
    out = os.path.join(LOGOS, name)
    old = b""
    if os.path.exists(out):
        with open(out, "rb") as f:
            old = f.read()
    if old != data:
        with open(out, "wb") as f:
            f.write(data)
    return "assets/tablelogos/" + name


def read_xlsx(path):
    import openpyxl
    wb = openpyxl.load_workbook(path, data_only=True)
    ws = wb[wb.sheetnames[0]]

    def cell(r, c=2):
        return clean(ws.cell(r, c).value)

    subject = cell(2)
    strap = cell(3)
    kind = strap.split("•")[0].strip() if strap else ""
    date_range = ""
    for r in range(4, 10):
        if clean(ws.cell(r, 1).value).upper().startswith("DATE RANGE"):
            date_range = cell(r)
            break

    # the data grid starts at the first row that has 3+ filled cells after row 8
    start = None
    for r in range(9, min(ws.max_row, 30) + 1):
        filled = sum(1 for c in range(1, ws.max_column + 1)
                     if ws.cell(r, c).value not in (None, ""))
        if filled >= 3:
            start = r
            break
    if start is None:
        return None

    ncols = min(ws.max_column, PREVIEW_COLS)
    head = [clean(ws.cell(start, c).value) for c in range(1, ncols + 1)]
    rows = []
    for r in range(start + 1, min(ws.max_row, start + PREVIEW_ROWS) + 1):
        row = [clean(ws.cell(r, c).value) for c in range(1, ncols + 1)]
        if any(row):
            rows.append(row)

    logo = save_logo(path, os.path.splitext(os.path.basename(path))[0])

    return {
        "logo": logo,
        "subject": subject,
        "kind": kind,
        "date_range": date_range,
        "year": year_from(date_range) or year_from(strap),
        "note": strap,
        "head": head,
        "rows": rows,
        "total_rows": max(ws.max_row - start, 0),
    }


def read_csv(path):
    with open(path, newline="", encoding="utf-8-sig", errors="replace") as f:
        reader = list(csv.reader(f))
    if not reader:
        return None
    head = [clean(c) for c in reader[0][:PREVIEW_COLS]]
    rows = [[clean(c) for c in r[:PREVIEW_COLS]]
            for r in reader[1:PREVIEW_ROWS + 1] if any(r)]
    name = os.path.splitext(os.path.basename(path))[0]
    return {
        "logo": "",
        "subject": name,
        "kind": "",
        "date_range": "",
        "year": year_from(name),
        "note": "",
        "head": head,
        "rows": rows,
        "total_rows": max(len(reader) - 1, 0),
    }


def collect():
    if not os.path.isdir(TABLES):
        return []
    out = []
    for n in sorted(os.listdir(TABLES), key=str.lower):
        if n.startswith(".") or n.lower() in ("readme.md", "index.html"):
            continue
        path = os.path.join(TABLES, n)
        if not os.path.isfile(path):
            continue
        low = n.lower()
        try:
            if low.endswith((".xlsx", ".xlsm")):
                t = read_xlsx(path)
            elif low.endswith((".csv", ".tsv")):
                t = read_csv(path)
            else:
                continue
        except Exception as e:                       # noqa: BLE001
            print(f"  skipped {n}: {e}")
            continue
        if not t:
            print(f"  skipped {n}: no data grid found")
            continue
        t["file"] = n
        t["size"] = human_size(os.path.getsize(path))
        out.append(t)
        print(f"  read {n}")
    return out


IMAGE_EXT = (".jpg", ".jpeg", ".png", ".webp", ".gif", ".avif")


def collect_gallery():
    if not os.path.isdir(GALLERY):
        return []
    out = []
    for n in sorted(os.listdir(GALLERY), key=str.lower):
        if n.startswith(".") or not n.lower().endswith(IMAGE_EXT):
            continue
        path = os.path.join(GALLERY, n)
        if os.path.isfile(path):
            out.append({
                "file": n,
                "name": os.path.splitext(n)[0],
                "size": human_size(os.path.getsize(path)),
            })
    return out


def write_json(path, payload, label):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    new = json.dumps(payload, indent=1, ensure_ascii=False)
    old = ""
    if os.path.exists(path):
        with open(path, encoding="utf-8") as f:
            old = f.read()
    if new != old:
        with open(path, "w", encoding="utf-8") as f:
            f.write(new)
        print(f"{label} updated.")
    else:
        print(f"{label} unchanged.")


def main():
    tables = collect()
    write_json(OUT, {"tables": tables}, f"tables.json ({len(tables)})")
    gallery = collect_gallery()
    write_json(GOUT, {"images": gallery}, f"gallery.json ({len(gallery)})")


if __name__ == "__main__":
    main()
