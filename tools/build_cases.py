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

import html
import os
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
            "blurb": read_text(os.path.join(abs_path, "about.txt")),
            "thumb": find_thumb(abs_path, name),
            "date": date,
            "has_files": os.path.isdir(os.path.join(abs_path, "Files")),
            "has_images": os.path.isdir(os.path.join(abs_path, "Images")),
        })

    cases.sort(key=lambda c: (c["date"] is not None, c["date"] or ""), reverse=True)
    return cases


def render(cases):
    if not cases:
        return '  <p class="empty">No cases published yet.</p>'

    out = []
    for c in cases:
        folder = html.escape(c["folder"], quote=True)
        tree = REPO_TREE + "/" + quote(c["folder"])
        title = html.escape(c["title"])
        date = c["date"].strftime("%B %-d, %Y") if c["date"] else ""
        thumb = html.escape(quote(c["thumb"]), quote=True) if c["thumb"] else ""

        img = (f'<img src="{thumb}" alt="">' if thumb
               else '<span class="noimg"></span>')

        btns = []
        if c["has_files"]:
            btns.append(f'<a class="btn" href="{tree}/Files">{FILES_SVG}<span>Files</span></a>')
        if c["has_images"]:
            btns.append(f'<a class="btn alt" href="{tree}/Images">{IMAGES_SVG}<span>Images</span></a>')
        if not btns:
            btns.append(f'<a class="btn" href="{tree}">{FILES_SVG}<span>Open</span></a>')

        blurb = (f'\n      <p class="blurb">{html.escape(c["blurb"])}</p>'
                 if c["blurb"] else "")

        out.append(
            f'  <article class="case">\n'
            f'    <a class="thumb" href="{tree}">{img}</a>\n'
            f'    <div class="body">\n'
            f'      <div class="head">\n'
            f'        <h3>{title}</h3>\n'
            f'        <div class="date">{date}</div>\n'
            f'      </div>{blurb}\n'
            f'      <div class="btns">\n'
            f'        ' + "\n        ".join(btns) + '\n'
            f'      </div>\n'
            f'    </div>\n'
            f'  </article>'
        )
    return "\n".join(out)


def main():
    with open(INDEX, encoding="utf-8") as f:
        page = f.read()

    start = page.find("<!-- CASES:START")
    end = page.find("<!-- CASES:END -->")
    if start == -1 or end == -1:
        sys.exit("index.html is missing the CASES:START / CASES:END markers.")

    start_line_end = page.index("\n", start) + 1
    new_body = render(collect()) + "\n  "
    updated = page[:start_line_end] + new_body + page[end:]

    if updated == page:
        print("No change.")
        return

    with open(INDEX, "w", encoding="utf-8") as f:
        f.write(updated)
    print("index.html updated.")


if __name__ == "__main__":
    main()
