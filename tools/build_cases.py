#!/usr/bin/env python3
"""Rebuilds the CASES list in index.html from the case folders in the repo.

A case folder is any top-level folder that is not hidden, not 'assets',
not 'tools', and does not start with '_'.

Inside a case folder:
  Files/          the documents            (optional)
  Images/         screenshots              (optional)
  <any image>     the thumbnail            (optional, first image found)
  about.txt       one or two lines of blurb (optional)
  title.txt       overrides the folder name (optional)
  date.txt        overrides the git date    (optional, e.g. 2026-03-14)

Everything else is worked out automatically.
"""

import hashlib
import html
import os
import zipfile
from urllib.parse import quote
import re
import subprocess
import sys
from datetime import datetime

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
# GitHub Pages does not list folders, so folder links must point at the repo.
REPO_TREE = "https://github.com/Vesper-Digital/Evidence-Archive/tree/main"
INDEX = os.path.join(ROOT, "index.html")
SKIP = {"assets", "tools", "node_modules", "docs"}
IMAGE_EXT = (".jpg", ".jpeg", ".png", ".webp", ".gif", ".avif")

FILES_SVG = ('<svg viewBox="0 0 24 24" aria-hidden="true">'
             '<path d="M14 2H7a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h10a2 2 0 0 0 2-2V7z"/>'
             '<path d="M14 2v5h5"/><path d="M9 13h6"/><path d="M9 17h6"/></svg>')
IMAGES_SVG = ('<svg viewBox="0 0 24 24" aria-hidden="true">'
              '<rect x="3" y="4" width="18" height="16" rx="2"/>'
              '<circle cx="8.5" cy="9.5" r="1.8"/>'
              '<path d="M21 16l-5-5-6 6-3-3-4 4"/></svg>')


def git_first_date(path):
    """Date the folder first appeared in the repo."""
    try:
        out = subprocess.run(
            ["git", "log", "--diff-filter=A", "--follow", "--format=%aI",
             "--reverse", "--", path],
            cwd=ROOT, capture_output=True, text=True, timeout=30)
        lines = [l for l in out.stdout.splitlines() if l.strip()]
        if lines:
            return datetime.fromisoformat(lines[0]).date()
    except Exception:
        pass
    return None


def pretty_title(name):
    name = re.sub(r"^\d{4}-\d{2}-\d{2}[ _-]+", "", name)
    name = re.sub(r"^\d+[ _.-]+", "", name)
    name = name.replace("-", " ").replace("_", " ")
    name = re.sub(r"\s+", " ", name).strip()
    return name.title() if name.islower() else name


def read_text(path):
    try:
        with open(path, encoding="utf-8") as f:
            return f.read().strip()
    except Exception:
        return ""


def find_thumb(folder_abs, folder_rel):
    names = sorted(os.listdir(folder_abs))
    preferred = [n for n in names if os.path.splitext(n)[0].lower()
                 in ("thumb", "thumbnail", "cover")]
    for n in preferred + names:
        if n.lower().endswith(IMAGE_EXT) and os.path.isfile(os.path.join(folder_abs, n)):
            return f"{folder_rel}/{n}"
    # fall back to an image inside Images/
    img_dir = os.path.join(folder_abs, "Images")
    if os.path.isdir(img_dir):
        for n in sorted(os.listdir(img_dir)):
            if n.lower().endswith(IMAGE_EXT):
                return f"{folder_rel}/Images/{n}"
    return None


URL_RE = re.compile(r"^\s*(https?://\S+)\s*$")


def split_about(text):
    """about.txt: any line that is only a URL becomes the video link."""
    blurb, video = [], ""
    for line in text.splitlines():
        m = URL_RE.match(line)
        if m and not video:
            video = m.group(1)
        else:
            blurb.append(line)
    return {"blurb": " ".join(l.strip() for l in blurb if l.strip()),
            "video": video}


def zip_case(folder):
    """Zip a case's Files/ and Images/ into assets/zips/. Returns a web path."""
    abs_folder = os.path.join(ROOT, folder)
    parts = []
    for sub in ("Files", "Images"):
        d = os.path.join(abs_folder, sub)
        if not os.path.isdir(d):
            continue
        for n in sorted(os.listdir(d)):
            f = os.path.join(d, n)
            if os.path.isfile(f) and not n.startswith("."):
                parts.append((f"{sub}/{n}", os.path.getsize(f), f))
    if not parts:
        return ""

    sig = hashlib.sha256(
        "|".join(f"{n}:{sz}" for n, sz, _ in parts).encode()).hexdigest()[:16]

    zips = os.path.join(ROOT, "assets", "zips")
    os.makedirs(zips, exist_ok=True)
    slug = re.sub(r"[^A-Za-z0-9._-]+", "-", folder).strip("-")
    zip_path = os.path.join(zips, slug + ".zip")
    sig_path = zip_path + ".sig"

    if os.path.exists(zip_path) and read_text(sig_path) == sig:
        return f"assets/zips/{quote(slug)}.zip"

    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED,
                         allowZip64=True) as z:
        for arc, _sz, full in parts:
            z.write(full, f"{folder}/{arc}")
    with open(sig_path, "w", encoding="utf-8") as f:
        f.write(sig)
    return f"assets/zips/{quote(slug)}.zip"


def collect():
    cases = []
    for name in sorted(os.listdir(ROOT)):
        abs_path = os.path.join(ROOT, name)
        if not os.path.isdir(abs_path):
            continue
        if name.startswith((".", "_")) or name in SKIP:
            continue

        date_override = read_text(os.path.join(abs_path, "date.txt"))
        date = None
        if date_override:
            try:
                date = datetime.fromisoformat(date_override.split()[0]).date()
            except ValueError:
                date = None
        if date is None:
            m = re.match(r"^(\d{4}-\d{2}-\d{2})", name)
            if m:
                date = datetime.fromisoformat(m.group(1)).date()
        if date is None:
            date = git_first_date(name)

        cases.append({
            "folder": name,
            "title": read_text(os.path.join(abs_path, "title.txt")) or pretty_title(name),
            **split_about(read_text(os.path.join(abs_path, "about.txt"))),
            "thumb": find_thumb(abs_path, name),
            "date": date,
            "has_files": os.path.isdir(os.path.join(abs_path, "Files")),
            "has_images": os.path.isdir(os.path.join(abs_path, "Images")),
            "zip": zip_case(name),
        })

    cases.sort(key=lambda c: (c["date"] is not None, c["date"] or ""), reverse=True)
    return cases


def render(cases):
    if not cases:
        return '  <p class="empty">No cases published yet.</p>'

    out = []
    for c in cases:
        folder = html.escape(c["folder"], quote=True)
        tree = quote(c["folder"]) + "/"
        vid = c.get("video") or ""
        thumb_href = html.escape(vid, quote=True) if vid else tree
        thumb_tgt = ' target="_blank" rel="noopener"' if vid else ""
        thumb_cls = " play" if vid else ""
        title = html.escape(c["title"])
        date = c["date"].strftime("%B %-d, %Y") if c["date"] else ""
        thumb = html.escape(quote(c["thumb"]), quote=True) if c["thumb"] else ""

        img = (f'<img src="{thumb}" alt="">' if thumb
               else '<span class="noimg"></span>')

        btns = []
        if c["has_files"]:
            btns.append(f'<a class="btn" href="{tree}#files">{FILES_SVG}<span>Files</span></a>')
        if c["has_images"]:
            btns.append(f'<a class="btn alt" href="{tree}#images">{IMAGES_SVG}<span>Images</span></a>')
        if not btns:
            btns.append(f'<a class="btn" href="{tree}">{FILES_SVG}<span>Open</span></a>')

        blurb = (f'\n      <p class="blurb">{html.escape(c["blurb"])}</p>'
                 if c["blurb"] else "")

        out.append(
            f'  <article class="case">\n'
            f'    <a class="thumb{thumb_cls}" href="{thumb_href}"{thumb_tgt}>{img}</a>\n'
            f'    <div class="body">\n'
            f'      <div class="head">\n'
            f'        <h3><a href="{tree}">{title}</a></h3>\n'
            f'        <div class="date">{date}</div>\n'
            f'      </div>{blurb}\n'
            f'      <div class="btns">\n'
            f'        ' + "\n        ".join(btns) + '\n'
            f'      </div>\n'
            f'    </div>\n'
            f'  </article>'
        )
    return "\n".join(out)


CASE_PAGE = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>__TITLE__ — Vesper Digital Evidence Archive</title>
<style>
  :root{--bg:#000;--line:#1c1c1c;--text:#e8e8e8;--muted:#8a8a8a;--red:#ff1f2d;--cyan:#19d6e8;--max:1480px}
  *{box-sizing:border-box;margin:0;padding:0}
  body{background:var(--bg);color:var(--text);font-family:"Barlow Condensed","Oswald","Archivo Narrow",Helvetica,Arial,sans-serif;font-size:20px;line-height:1.6;-webkit-font-smoothing:antialiased}
  .wrap{max-width:var(--max);margin:0 auto;padding:0 24px}
  .banner{display:grid;grid-template-columns:auto 1fr;width:100%;max-width:var(--max);margin:0 auto;background:#000}
  .banner img{display:block;width:100%;height:clamp(140px,16vw,230px);object-fit:cover}
  .banner .portrait{height:clamp(140px,16vw,230px);width:clamp(140px,16vw,230px);object-fit:cover}
  @media (max-width:640px){
    .banner{grid-template-columns:1fr}
    .banner .portrait{display:none}
  }
  .back{display:inline-block;margin:28px 0 10px;color:var(--cyan);text-decoration:none;font-size:18px;letter-spacing:.1em;text-transform:uppercase}
  .back:hover{text-decoration:underline}
  h1{font-size:clamp(30px,4.2vw,52px);font-weight:800;letter-spacing:.045em;text-transform:uppercase;line-height:1.05}
  .rule{height:3px;background:var(--red);margin:16px 0 22px}
  .meta{color:var(--red);font-size:clamp(16px,1.25vw,20px);letter-spacing:.16em;text-transform:uppercase;font-weight:700;margin-bottom:14px}
  .blurb{color:#d2d2d2;font-size:clamp(19px,1.5vw,25px);max-width:80ch;margin-bottom:12px}
  .sec{margin:46px 0 18px;display:flex;align-items:center;gap:18px}
  .sec h2{font-size:clamp(22px,2.4vw,30px);font-weight:800;letter-spacing:.14em;text-transform:uppercase;white-space:nowrap}
  .sec:after{content:"";flex:1;height:1px;background:var(--line)}
  ul.files{list-style:none;display:grid;gap:14px}
  ul.files a{display:grid;grid-template-columns:auto 1fr auto auto;align-items:center;gap:20px;
    padding:22px 24px;border:1px solid #2a2a2a;background:#0b0b0b;color:#fff;text-decoration:none;
    transition:border-color .16s ease,background .16s ease}
  ul.files a:hover{border-color:var(--red);background:#120404}
  ul.files svg{width:26px;height:26px;stroke:var(--red);fill:none;stroke-width:1.8;flex:none}
  ul.files .nm{font-size:clamp(19px,1.5vw,25px);overflow-wrap:anywhere;line-height:1.3}
  ul.files .sz{color:#fff;font-size:18px;white-space:nowrap;letter-spacing:.1em}
  ul.files .dl{display:flex;align-items:center;gap:10px;color:var(--red);font-size:16px;
    font-weight:700;letter-spacing:.18em;text-transform:uppercase;white-space:nowrap}
  ul.files a:hover .dl{color:#fff}
  @media (max-width:720px){
    ul.files a{grid-template-columns:auto 1fr;row-gap:10px}
    ul.files .sz,ul.files .dl{grid-column:2}
  }
  .top{display:grid;grid-template-columns:1fr 1fr;gap:16px;margin:26px 0 6px;max-width:760px}
  .top a{display:flex;align-items:center;justify-content:center;gap:14px;padding:18px;
    border:2px solid var(--red);color:#fff;text-decoration:none;font-size:clamp(16px,1.3vw,20px);
    font-weight:700;letter-spacing:.18em;text-transform:uppercase;
    transition:background .16s ease,color .16s ease}
  .top a:hover{background:var(--red);color:#fff}
  .top a.alt{border-color:#3a3a3a;color:#cfcfcf}
  .top a.alt:hover{background:#fff;color:#000;border-color:#fff}
  .top svg{width:1.15em;height:1.15em;flex:none;stroke:currentColor;fill:none;stroke-width:1.9}
  @media (max-width:640px){.top{grid-template-columns:1fr}}
  .shots{display:grid;grid-template-columns:repeat(auto-fill,minmax(300px,1fr));gap:18px}
  .shots a{display:block;background:#0d0d0d}
  .shots img{display:block;width:100%;height:auto}
  footer{margin:70px 0 60px;padding-top:24px;border-top:1px solid var(--line);color:var(--muted);font-size:18px;display:flex;flex-wrap:wrap;gap:10px 26px;justify-content:space-between}
  footer a{color:var(--cyan);text-decoration:none}
  footer a:hover{text-decoration:underline}
</style>
</head>
<body>
<div class="banner"><img class="portrait" src="__UP__assets/portrait.jpg" alt=""><img src="__UP__assets/banner.png" alt="Vesper Digital"></div>
<div class="wrap">
  <a class="back" href="__UP__">&larr; All cases</a>
  <h1>__TITLE__</h1>
  <div class="rule"></div>
  <div class="meta">__DATE__</div>
__BLURB__
__ACTIONS__
__BODY__
  <footer>
    <div>Vesper Digital — Media · Power · Accountability</div>
    <div><a href="__UP__">Evidence Archive</a></div>
  </footer>
</div>
</body>
</html>
"""


DOWNLOAD_SVG = ('<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M12 3v12"/><path d="M7 11l5 5 5-5"/><path d="M4 20h16"/></svg>')


def human_size(n):
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024 or unit == "GB":
            return f"{n:.0f} {unit}" if unit == "B" else f"{n:,.0f} {unit}"
        n /= 1024.0


def list_dir(abs_dir):
    if not os.path.isdir(abs_dir):
        return []
    out = []
    for n in sorted(os.listdir(abs_dir)):
        full = os.path.join(abs_dir, n)
        if n.startswith(".") or not os.path.isfile(full):
            continue
        if n.lower() in ("readme.md", "index.html"):
            continue
        out.append((n, os.path.getsize(full)))
    return out


PLAY_SVG = ('<svg viewBox="0 0 24 24" aria-hidden="true"><circle cx="12" cy="12" r="9"/><path d="M10 8.5l6 3.5-6 3.5z"/></svg>')
ZIP_SVG = ('<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M12 3v12"/><path d="M7 11l5 5 5-5"/><path d="M4 20h16"/></svg>')


def write_case_page(case):
    folder = case["folder"]
    abs_folder = os.path.join(ROOT, folder)
    files = list_dir(os.path.join(abs_folder, "Files"))
    images = list_dir(os.path.join(abs_folder, "Images"))

    body = []
    if files:
        body.append('  <div class="sec" id="files"><h2>Files</h2></div>')
        body.append('  <ul class="files">')
        for n, sz in files:
            body.append(
                f'    <li><a href="Files/{quote(n)}" download>'
                f'{DOWNLOAD_SVG}'
                f'<span class="nm">{html.escape(n)}</span>'
                f'<span class="sz">{human_size(sz)}</span>'
                f'<span class="dl">Download</span></a></li>')
        body.append("  </ul>")
    if images:
        body.append('  <div class="sec" id="images"><h2>Images</h2></div>')
        body.append('  <div class="shots">')
        for n, _sz in images:
            body.append(f'    <a href="Images/{quote(n)}"><img src="Images/{quote(n)}" alt="" loading="lazy"></a>')
        body.append("  </div>")
    if not body:
        body.append('  <p class="blurb">No documents published for this case yet.</p>')

    blurb = (f'  <p class="blurb">{html.escape(case["blurb"])}</p>'
             if case["blurb"] else "")

    acts = []
    if case.get("video"):
        acts.append(f'    <a href="{html.escape(case["video"], quote=True)}" '
                    f'target="_blank" rel="noopener">{PLAY_SVG}'
                    f'<span>Watch the video</span></a>')
    if case.get("zip"):
        acts.append(f'    <a class="alt" href="../{case["zip"]}" download>'
                    f'{ZIP_SVG}<span>Download all</span></a>')
    actions = ('  <div class="top">\n' + "\n".join(acts) + '\n  </div>') if acts else ""
    date = case["date"].strftime("%B %-d, %Y") if case["date"] else ""

    page = (CASE_PAGE
            .replace("__TITLE__", html.escape(case["title"]))
            .replace("__DATE__", date)
            .replace("__BLURB__", blurb)
            .replace("__ACTIONS__", actions)
            .replace("__BODY__", "\n".join(body))
            .replace("__UP__", "../"))

    target = os.path.join(abs_folder, "index.html")
    old = ""
    if os.path.exists(target):
        with open(target, encoding="utf-8") as f:
            old = f.read()
    if old != page:
        with open(target, "w", encoding="utf-8") as f:
            f.write(page)
        return True
    return False


def main():
    with open(INDEX, encoding="utf-8") as f:
        page = f.read()

    cases = collect()
    for c in cases:
        write_case_page(c)

    start = page.find("<!-- CASES:START")
    end = page.find("<!-- CASES:END -->")
    if start == -1 or end == -1:
        sys.exit("index.html is missing the CASES:START / CASES:END markers.")

    start_line_end = page.index("\n", start) + 1
    new_body = render(cases) + "\n  "
    updated = page[:start_line_end] + new_body + page[end:]

    if updated == page:
        print("No change.")
        return

    with open(INDEX, "w", encoding="utf-8") as f:
        f.write(updated)
    print("index.html updated.")


if __name__ == "__main__":
    main()
