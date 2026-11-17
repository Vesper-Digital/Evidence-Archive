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
import json
import os
import shutil
import unicodedata
import zipfile
from urllib.parse import quote
import re
import subprocess
import sys
from datetime import datetime

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
# GitHub Pages does not list folders, so folder links must point at the repo.
REPO_TREE = "https://github.com/Vesper-Digital/Evidence-Archive/tree/main"
# the live address, used for the link preview cards other sites draw
SITE = "https://vesper-digital.github.io/Evidence-Archive/"
DEFAULT_DESC = "The source documents behind every Vesper Digital video."
INDEX = os.path.join(ROOT, "index.html")
SKIP = {"assets", "tools", "node_modules", "docs", "Tables", "Gallery", "s"}
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


YT_RE = re.compile(
    r"(?:youtu\.be/|youtube\.com/(?:watch\?v=|live/|shorts/|embed/))"
    r"([A-Za-z0-9_-]{6,})")


def youtube_embed(url):
    """Turn any YouTube link into an embeddable one. '' if not YouTube."""
    m = YT_RE.search(url or "")
    return f"https://www.youtube.com/embed/{m.group(1)}?autoplay=1&rel=0&cc_load_policy=0&modestbranding=1" if m else ""


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
            "has_images": bool(list_dir(os.path.join(abs_path, "Images"))),
            "zip": zip_case(name),
        })

    cases.sort(key=lambda c: (c["date"] is not None, c["date"] or ""), reverse=True)
    return cases


def render(cases):
    if not cases:
        return '  <p class="empty">No cases published yet.</p>'

    out = []
    for i, c in enumerate(cases):
        folder = html.escape(c["folder"], quote=True)
        base = 1080 + i * 320
        tree = "s/" + SLUG_FOR[c["folder"] + "/"] + "/"
        vid = c.get("video") or ""
        thumb_href = html.escape(vid, quote=True) if vid else tree
        thumb_tgt = ' target="_blank" rel="noopener"' if vid else ""
        thumb_cls = " play" if vid else ""
        emb = youtube_embed(vid)
        thumb_data = f' data-embed="{html.escape(emb, quote=True)}"' if emb else ""
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
        if c.get("zip"):
            btns.append(f'<a class="btn alt" href="{c["zip"]}" download>'
                        f'{ZIP_SVG}<span>Download all</span></a>')
        if not btns:
            btns.append(f'<a class="btn" href="{tree}">{FILES_SVG}<span>Open</span></a>')
        ncls = f' n{len(btns)}'
        share = (f'<button class="share casehare" type="button" title="Copy link" '
                 f'data-share="{tree}">{SHARE_SVG}</button>')

        blurb = (f'\n      <p class="blurb">{html.escape(c["blurb"])}</p>'
                 if c["blurb"] else "")

        out.append(
            f'  <article class="case">\n'
            f'    <a class="thumb{thumb_cls} rz" data-rz="{base}" href="{thumb_href}"{thumb_tgt}{thumb_data}>{img}</a>\n'
            f'    <div class="body rz" data-rz="{base + 200}">\n'
            f'      <div class="head">\n'
            f'        <h3><a href="{tree}">{title}</a></h3>\n'
            f'        <div class="date">{date}{share}</div>\n'
            f'      </div>{blurb}\n'
            f'      <div class="btns{ncls}">\n'
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
<meta name="description" content="__OGDESC__">
<!-- preview card. the image has to be a full https address or nothing shows -->
<meta property="og:type" content="article">
<meta property="og:site_name" content="Vesper Digital Investigative Archive">
<meta property="og:title" content="__OGTITLE__">
<meta property="og:description" content="__OGDESC__">
<meta property="og:url" content="__OGURL__">
<meta property="og:image" content="__OGIMG__">
<meta name="twitter:card" content="summary_large_image">
<meta name="twitter:title" content="__OGTITLE__">
<meta name="twitter:description" content="__OGDESC__">
<meta name="twitter:image" content="__OGIMG__">
<style>
  :root{--bg:#000;--line:#1c1c1c;--text:#e8e8e8;--muted:#8a8a8a;--red:#ff1f2d;--cyan:#19d6e8;--max:1480px;--yellow:#ffd60a;--cut:12px}
  *{box-sizing:border-box;margin:0;padding:0}
  body{background:var(--bg);color:var(--text);font-family:"Barlow Condensed","Oswald","Archivo Narrow",Helvetica,Arial,sans-serif;font-size:20px;line-height:1.6;-webkit-font-smoothing:antialiased}
  .wrap{max-width:var(--max);margin:0 auto;padding:0 24px}
  /* ======================================================================
     NAV — one bar, sticky, on every page. Wide screens show the row;
     narrow screens collapse it into the slide-out panel.
     ====================================================================== */
  .nav{position:sticky;top:0;z-index:60;background:rgba(0,0,0,.94);
    border-bottom:1px solid #151515;-webkit-backdrop-filter:blur(10px);backdrop-filter:blur(10px)}
  .navin{max-width:var(--max);margin:0 auto;padding:11px 24px;
    display:flex;align-items:center;gap:12px}

  .links{display:flex;align-items:center;justify-content:flex-end;gap:10px;flex:1;min-width:0}
  .links a{
    position:relative;display:inline-flex;align-items:center;
    background:#fff;text-decoration:none;flex:none;
    clip-path:polygon(var(--cut) 0,100% 0,100% calc(100% - var(--cut)),calc(100% - var(--cut)) 100%,0 100%,0 var(--cut));
    transition:background .16s ease;
  }
  .links a::before{content:"";position:absolute;inset:1px;background:#070707;
    clip-path:polygon(calc(var(--cut) - 1px) 0,100% 0,100% calc(100% - var(--cut) + 1px),calc(100% - var(--cut) + 1px) 100%,0 100%,0 calc(var(--cut) - 1px));
    transition:background .16s ease}
  .links a span{position:relative;z-index:1;display:inline-flex;align-items:center;
    gap:10px;padding:7px 25px;line-height:28px;
    font-size:18px;font-weight:700;letter-spacing:.2em;text-transform:uppercase;
    color:#b9b9b9;white-space:nowrap;transition:color .16s ease}
  .links a:hover{background:var(--red)}
  .links a:hover span{color:#fff}
  .links a.on{background:var(--red)}
  .links a.on span{color:#fff}
  .links a.on::before{background:#140105}

  .links a.donate{margin-left:50px;background:var(--yellow)}
  .links a.donate svg{width:22px;height:22px;flex:none;fill:none;
    stroke:currentColor;stroke-width:1.8}

  /* X and YouTube carry an icon but otherwise match every other item */
  .links a.ico b{font:inherit;font-size:inherit;letter-spacing:inherit}
  .links a.ico svg{width:20px;height:20px;flex:none;fill:currentColor}
  .links a.yt svg{width:27px;height:27px}
  .links a.donate span{color:var(--yellow);letter-spacing:.22em}
  .links a.donate:hover::before{background:var(--yellow)}
  .links a.donate:hover span{color:#000}

  /* the three-line button and the panel chrome, hidden on wide screens */
  .burger,.navclose,.scrim,.panelhead{display:none}

  /* ---- narrow, or a short landscape phone: slide-out panel ---- */
  @media (max-width:900px), (max-height:520px) and (orientation:landscape){
    /* a blurred ancestor would trap the fixed panel inside the bar, and the
       bar's own stacking has to sit above the scrim or the panel is dimmed */
    .nav{-webkit-backdrop-filter:none;backdrop-filter:none;background:#000;z-index:80}
    .navin{padding:9px 16px;justify-content:flex-end}
    .burger{
      display:inline-flex;flex-direction:column;justify-content:center;gap:5px;
      width:46px;height:40px;padding:0 11px;cursor:pointer;
      background:#2b2b2b;border:0;position:relative;
      clip-path:polygon(10px 0,100% 0,100% calc(100% - 10px),calc(100% - 10px) 100%,0 100%,0 10px);
    }
    .burger::before{content:"";position:absolute;inset:1px;background:#070707;
      clip-path:polygon(9px 0,100% 0,100% calc(100% - 9px),calc(100% - 9px) 100%,0 100%,0 9px)}
    .burger i{position:relative;z-index:1;display:block;height:2px;background:#e8e8e8;
      transition:transform .24s ease,opacity .18s ease}
    .burger[aria-expanded="true"] i:nth-child(1){transform:translateY(7px) rotate(45deg)}
    .burger[aria-expanded="true"] i:nth-child(2){opacity:0}
    .burger[aria-expanded="true"] i:nth-child(3){transform:translateY(-7px) rotate(-45deg)}

    .links{
      position:fixed;top:0;right:0;bottom:0;width:min(84vw,350px);
      flex-direction:column;align-items:stretch;justify-content:flex-start;
      gap:12px;padding:20px 20px calc(20px + env(safe-area-inset-bottom));
      background:linear-gradient(180deg,#0d0d0d 0%,#050505 100%);
      border-left:2px solid var(--red);box-shadow:-24px 0 60px rgba(0,0,0,.8);
      transform:translateX(100%);transition:transform .3s cubic-bezier(.33,1,.68,1);
      overflow-y:auto;z-index:70;
    }
    .links.open{transform:none}
    .links a{width:100%}
    .links a span{width:100%;padding:16px 18px;font-size:16px}
    .links a.donate{margin-left:0;margin-top:6px}
    .links a.ico span{padding:11px 18px}

    .panelhead{display:flex;align-items:center;justify-content:space-between;
      padding-bottom:4px;border-bottom:1px solid #1d1d1d;margin-bottom:6px}
    .panelhead b{font-size:13px;font-weight:700;letter-spacing:.24em;
      text-transform:uppercase;color:var(--muted)}
    .navclose{display:inline-flex;align-items:center;justify-content:center;
      width:38px;height:38px;background:none;border:1px solid #2a2a2a;color:#cfcfcf;
      cursor:pointer;padding:0}
    .navclose:hover{background:#fff;color:#000;border-color:#fff}
    .navclose svg{width:17px;height:17px;stroke:currentColor;fill:none;stroke-width:2.2}

    /* items drift in behind the panel */
    .links.open > *{animation:navin .34s both}
    .links.open > *:nth-child(2){animation-delay:.05s}
    .links.open > *:nth-child(3){animation-delay:.09s}
    .links.open > *:nth-child(4){animation-delay:.13s}
    .links.open > *:nth-child(5){animation-delay:.17s}
    .links.open > *:nth-child(6){animation-delay:.21s}
    @keyframes navin{from{opacity:0;transform:translateX(14px)}to{opacity:1;transform:none}}

    .scrim{display:block;position:fixed;inset:0;z-index:65;background:rgba(0,0,0,.62);
      -webkit-backdrop-filter:blur(3px);backdrop-filter:blur(3px);
      opacity:0;pointer-events:none;transition:opacity .3s ease}
    .scrim.on{opacity:1;pointer-events:auto}
  }

  /* short landscape phones: the panel has to scroll, not stretch */
  @media (max-height:460px) and (orientation:landscape){
    .links a span{padding:11px 16px;font-size:15px}
    .links{gap:9px;padding-top:14px}
  }

  .banner{display:grid;grid-template-columns:auto 1fr;width:100%;max-width:var(--max);margin:20px auto 0;background:#000}
  .banner img{display:block;width:100%;height:clamp(140px,16vw,230px);object-fit:cover}
  .banner .portrait{height:clamp(140px,16vw,230px);width:clamp(140px,16vw,230px);object-fit:cover}
  @media (max-width:640px){
    .banner{grid-template-columns:1fr}
    .banner .portrait{display:none}
  }
  .back{position:relative;display:inline-flex;align-items:center;gap:14px;
    margin:30px 0 24px;padding:14px 26px 14px 22px;border:0;background:var(--red);
    color:#fff;text-decoration:none;font-size:clamp(16px,1.25vw,19px);font-weight:700;
    letter-spacing:.2em;text-transform:uppercase;
    clip-path:polygon(16px 0, 100% 0, 100% 100%, 0 100%, 0 16px);
    transition:color .16s ease}
  .back::before{content:"";position:absolute;inset:2px;background:#000;
    clip-path:polygon(14px 0, 100% 0, 100% 100%, 0 100%, 0 14px);
    transition:background .16s ease}
  .back > *{position:relative;z-index:1}
  .back:hover::before{background:var(--red)}
  .back svg{width:22px;height:22px;flex:none;stroke:currentColor;fill:none;stroke-width:2.2}
  h1{font-size:clamp(30px,4.2vw,52px);font-weight:800;letter-spacing:.045em;text-transform:uppercase;line-height:1.05}
  .rule{height:3px;background:var(--red);margin:16px 0 22px}
  .meta{color:var(--red);font-size:clamp(16px,1.25vw,20px);letter-spacing:.16em;text-transform:uppercase;font-weight:700;margin-bottom:14px}
  .blurb{color:#d2d2d2;font-size:clamp(19px,1.5vw,25px);max-width:80ch;margin-bottom:12px}
  .panel{
    margin:56px 0 0;
    padding:4px 26px 30px;
    border:1px solid #1f1f1f;
    background:linear-gradient(180deg, rgba(255,255,255,.022), rgba(255,255,255,0) 160px);
    clip-path:polygon(26px 0, 100% 0, 100% 100%, 0 100%, 0 26px);
  }
  .sec{margin:26px 0 20px;display:flex;align-items:center;gap:18px}
  .sec h2{font-size:clamp(22px,2.4vw,30px);font-weight:800;letter-spacing:.14em;text-transform:uppercase;white-space:nowrap}
  .sec:after{content:"";flex:1;height:1px;background:var(--line)}
  ul.files{list-style:none;display:grid;gap:14px}
  ul.files li{display:flex;align-items:stretch;gap:10px}
  ul.files li > a{flex:1;min-width:0}
  .rshare{flex:none;width:58px;cursor:pointer;background:#0b0b0b;
    border:2px solid #3a3a3a;color:#cfcfcf;display:flex;align-items:center;
    justify-content:center;padding:0}
  .rshare:hover{background:#fff;color:#000;border-color:#fff}
  .rshare.done{background:var(--red);border-color:var(--red);color:#fff}
  ul.files .rshare svg,.sec .rshare svg{width:21px;height:21px;
    stroke:currentColor;fill:none;stroke-width:2}
  .sec .rshare{width:52px;height:44px}
  @media (max-width:720px){ .rshare{width:48px} }
  ul.files a{position:relative;display:grid;grid-template-columns:auto 1fr auto auto;
    align-items:center;gap:20px;padding:22px 24px;border:0;background:var(--red);
    color:#fff;text-decoration:none;
    clip-path:polygon(22px 0, 100% 0, 100% 100%, 0 100%, 0 22px)}
  ul.files a::before{content:"";position:absolute;inset:2px;background:#0b0b0b;
    clip-path:polygon(20px 0, 100% 0, 100% 100%, 0 100%, 0 20px);
    transition:background .16s ease}
  ul.files a > *{position:relative;z-index:1}
  ul.files a:hover::before{background:var(--red)}
  ul.files a:hover svg{stroke:#fff}
  ul.files a:hover .sz,ul.files a:hover .dl{color:#fff}
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
  .top a{position:relative;display:flex;align-items:center;justify-content:center;gap:14px;
    padding:18px;border:0;background:var(--red);color:#fff;text-decoration:none;
    font-size:clamp(16px,1.3vw,20px);
    clip-path:polygon(18px 0, 100% 0, 100% 100%, 0 100%, 0 18px);
    font-weight:700;letter-spacing:.18em;text-transform:uppercase;
    transition:color .16s ease}
  .top a::before{content:"";position:absolute;inset:2px;background:#000;
    clip-path:polygon(16px 0, 100% 0, 100% 100%, 0 100%, 0 16px);
    transition:background .16s ease}
  .top a > *{position:relative;z-index:1}
  .top a:hover::before{background:var(--red)}
  .top a.alt{background:#3a3a3a;color:#cfcfcf}
  .top a.alt:hover{color:#000}
  .top a.alt:hover::before{background:#fff}
  .top svg{width:1.15em;height:1.15em;flex:none;stroke:currentColor;fill:none;stroke-width:1.9}
  @media (max-width:640px){.top{grid-template-columns:1fr}}
  .shots{margin-top:22px;display:grid;grid-template-columns:repeat(auto-fill,minmax(300px,1fr));gap:18px}
  .shots a{display:block;background:#0d0d0d}
  .shots img{display:block;width:100%;height:auto}
  /* ENTRANCE */
  @keyframes rise{from{opacity:0;transform:translateY(22px)}to{opacity:1;transform:none}}
  .rz{opacity:0}
  .rz.in{animation:rise .9s cubic-bezier(.16,.72,.24,1) forwards}

  footer{margin:70px 0 60px;padding-top:24px;border-top:1px solid var(--line);color:var(--muted);font-size:18px;display:flex;flex-wrap:wrap;gap:10px 26px;justify-content:space-between}
  footer a{color:var(--cyan);text-decoration:none}
  footer a:hover{text-decoration:underline}
  /* ======================================================================
     NARROW SCREENS — the title, the date and the buttons each get their
     own line rather than being squeezed side by side and cut off.
     ====================================================================== */
  @media (max-width:700px){
    .wrap{padding:0 16px}
    .intro{padding:28px 0 0}
    .case .head{flex-direction:column;align-items:flex-start;gap:10px}
    .case .date{width:100%;justify-content:space-between;white-space:normal}
    .case h3{font-size:clamp(21px,5.6vw,27px)}
    .case .blurb{font-size:17px}
    .btns,.btns.n2,.btns.n3{grid-template-columns:1fr;gap:10px}
    .btn{padding:13px 16px}
    .sortbar{flex-wrap:wrap;gap:8px}
    .howto{margin-bottom:22px}
    footer{font-size:16px}
  }

  /* ======================================================================
     LANDSCAPE PHONES — the viewport is wide but very short, so the vw-based
     sizes blow up. Pin them to something sane and let the page scroll.
     ====================================================================== */
  @media (max-height:520px) and (orientation:landscape){
    body{font-size:17px}
    .banner img,.banner .portrait{height:120px}
    .banner .portrait{width:120px}
    .intro{padding:22px 0 0}
    .intro h1{font-size:30px}
    .lede{font-size:20px}
    .intro p{font-size:17px}
    .case h3{font-size:22px}
    .case .blurb{font-size:16px}
    .case .date{font-size:13px}
    .btn{padding:11px 14px;font-size:15px}
    .tcard h3{font-size:19px}
    .vw-inner{height:88vh}
  }

  /* nothing should ever be wider than the screen */
  html,body{max-width:100%;overflow-x:hidden}
  img,video,iframe{max-width:100%}
</style>
</head>
<body>
<nav class="nav">
  <div class="navin">
    <button class="burger" id="burger" type="button" aria-label="Menu" aria-expanded="false" aria-controls="links"><i></i><i></i><i></i></button>
    <div class="links" id="links">
      <div class="panelhead"><b>Menu</b>
        <button class="navclose" id="navclose" type="button" aria-label="Close menu"><svg viewBox="0 0 24 24" aria-hidden="true"><path d="M6 6l12 12M18 6L6 18"/></svg></button>
      </div>
      <a href="https://vesper-digital.github.io/"><span>Home</span></a>
      <a href="__UP__#cases"><span>Cases</span></a>
      <a href="__UP__#tables"><span>DSX Tables</span></a>
      <a href="__UP__#gallery"><span>Gallery</span></a>
      <a class="ico x" href="https://x.com/vesperdigital" target="_blank" rel="noopener" aria-label="X"><span><svg viewBox="0 0 24 24" aria-hidden="true"><path d="M18.9 2H22l-7 8.1L23.3 22h-6.6l-5.1-6.8L5.7 22H2.6l7.5-8.6L1.9 2h6.8l4.6 6.2L18.9 2Zm-1.1 18h1.7L7.3 3.7H5.5L17.8 20Z"/></svg><b>X.com</b></span></a>
      <a class="ico yt" href="https://www.youtube.com/@Vesperdigital" target="_blank" rel="noopener" aria-label="YouTube"><span><svg viewBox="0 0 24 24" aria-hidden="true"><path d="M23 12s0-3.6-.5-5.3a2.8 2.8 0 0 0-2-2C18.8 4.2 12 4.2 12 4.2s-6.8 0-8.5.5a2.8 2.8 0 0 0-2 2C1 8.4 1 12 1 12s0 3.6.5 5.3a2.8 2.8 0 0 0 2 2c1.7.5 8.5.5 8.5.5s6.8 0 8.5-.5a2.8 2.8 0 0 0 2-2C23 15.6 23 12 23 12ZM9.8 15.3V8.7l5.7 3.3-5.7 3.3Z"/></svg><b>YouTube</b></span></a>
      <a class="donate" href="https://buymeacoffee.com/vesperdigital" target="_blank" rel="noopener"><span><svg viewBox="0 0 24 24" aria-hidden="true"><path d="M4 8h13v6a5 5 0 0 1-5 5H9a5 5 0 0 1-5-5V8Z"/><path d="M17 10h1.6a2.4 2.4 0 0 1 0 4.8H17"/><path d="M8 2.6v2.2M12 2.6v2.2" stroke-linecap="round"/></svg>Support</span></a>
    </div>
  </div>
</nav>
<div class="scrim" id="scrim"></div>
<div class="banner rz" data-rz="0"><img class="portrait" src="__UP__assets/portrait.jpg" alt=""><img src="__UP__assets/banner.png" alt="Vesper Digital"></div>
<div class="wrap">
  <div class="rz" data-rz="320">
    <a class="back" href="__UP__"><svg viewBox="0 0 24 24" aria-hidden="true"><path d="M20 12H4M10 6l-6 6 6 6"/></svg><span>All cases</span></a>
    <h1>__TITLE__</h1>
    <div class="meta">__DATE__</div>
  </div>
__BLURB__
__ACTIONS__
__BODY__
  <footer class="rz" data-rz="260">
    <div>Vesper Digital — Media · Power · Accountability</div>
    <div><a href="__UP__">Evidence Archive</a></div>
  </footer>
</div>
<script>
(function(){
  // ---- the menu ----------------------------------------------------------
  var burger = document.getElementById('burger'),
      navlinks = document.getElementById('links'),
      scrim = document.getElementById('scrim'),
      navclose = document.getElementById('navclose');
  function openNav(){
    navlinks.classList.add('open'); scrim.classList.add('on');
    burger.setAttribute('aria-expanded','true');
    document.body.style.overflow = 'hidden';
  }
  function closeNav(){
    if (!navlinks.classList.contains('open')) return;
    navlinks.classList.remove('open'); scrim.classList.remove('on');
    burger.setAttribute('aria-expanded','false');
    document.body.style.overflow = '';
  }
  burger.addEventListener('click', function(){
    navlinks.classList.contains('open') ? closeNav() : openNav();
  });
  navclose.addEventListener('click', closeNav);
  scrim.addEventListener('click', closeNav);
  navlinks.addEventListener('click', function(e){ if (e.target.closest('a')) closeNav(); });
  document.addEventListener('keydown', function(e){ if (e.key === 'Escape') closeNav(); });
  var wide = window.matchMedia('(min-width:901px) and (min-height:521px)');
  (wide.addEventListener ? wide.addEventListener.bind(wide,'change') : wide.addListener.bind(wide))(
    function(e){ if (e.matches) closeNav(); });
})();
</script>
<script>
(function(){
  // the Files / Images buttons each show only their own section
  function apply(){
    var h = location.hash.replace('#','').toLowerCase(),
        f = document.getElementById('files'),
        i = document.getElementById('images');
    if (!f || !i) return;
    if (h === 'files')  { f.style.display = ''; i.style.display = 'none'; }
    else if (h === 'images') { f.style.display = 'none'; i.style.display = ''; }
    else { f.style.display = ''; i.style.display = ''; }
    window.scrollTo(0, 0);
  }
  apply();
  window.addEventListener('hashchange', apply);
})();
</script>
<script>
(function(){
  function done(btn){
    btn.classList.add('done');
    setTimeout(function(){ btn.classList.remove('done'); }, 1400);
  }
  function fallback(text, btn){
    var a = document.createElement('textarea');
    a.value = text; a.style.position = 'fixed'; a.style.opacity = '0';
    document.body.appendChild(a); a.select();
    try { document.execCommand('copy'); done(btn); } catch (e) {}
    document.body.removeChild(a);
  }
  document.addEventListener('click', function(e){
    var sh = e.target.closest('.rshare');
    if (!sh) return;
    e.preventDefault();
    var url = new URL(sh.getAttribute('data-share'), location.href).href;
    if (navigator.clipboard && navigator.clipboard.writeText) {
      navigator.clipboard.writeText(url).then(function(){ done(sh); },
                                             function(){ fallback(url, sh); });
    } else {
      fallback(url, sh);
    }
  });
})();
</script>
<script>
(function(){
  var items = document.querySelectorAll('.rz');
  if (!items.length) return;

  if (!('IntersectionObserver' in window)) {
    [].forEach.call(items, function(el){ el.classList.add('in'); });
    return;
  }

  var io = new IntersectionObserver(function(entries){
    entries.forEach(function(e){
      if (!e.isIntersecting) return;
      var el = e.target;
      var d = parseInt(el.getAttribute('data-rz') || '0', 10);
      setTimeout(function(){ el.classList.add('in'); }, d);
      io.unobserve(el);
    });
  }, {rootMargin:'0px 0px -8% 0px', threshold:0.05});

  [].forEach.call(items, function(el){ io.observe(el); });
})();
</script>
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


SHARE_SVG = ('<svg viewBox="0 0 24 24" aria-hidden="true"><circle cx="18" cy="5" r="2.6"/><circle cx="6" cy="12" r="2.6"/><circle cx="18" cy="19" r="2.6"/><path d="M8.3 10.8l7.4-4.3M8.3 13.2l7.4 4.3"/></svg>')

BACK_SVG = ('<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M20 12H4M10 6l-6 6 6 6"/></svg>')

FOLDER_SVG = ('<svg viewBox="0 0 24 24" aria-hidden="true">'
              '<path d="M3 7a2 2 0 0 1 2-2h4l2 2.5h8a2 2 0 0 1 2 2V18a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z"/>'
              '</svg>')


# ---------------------------------------------------------------------------
# Short share links.
#
# The real address of a nested folder is a wall of %20s. Every case, folder
# and file also gets a tidy address under /s/, which is a one-line page that
# sends the browser on to the real one:
#
#   .../Evidence-Archive/s/nsira-pdfs/
#
SHORTS_DIR = os.path.join(ROOT, "s")
SHORTS = {}

REDIRECT = """<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<meta name="robots" content="noindex">
<title>Opening…</title>
<meta http-equiv="refresh" content="0; url=__T__">
<link rel="canonical" href="__T__">
<script>location.replace("__T__");</script>
<style>body{background:#000;color:#e8e8e8;font:16px/1.5 Helvetica,Arial,sans-serif;
padding:40px}a{color:#ff1f2d}</style>
</head><body><p>Opening the archive. <a href="__T__">Go there now.</a></p></body></html>
"""


TAKEN = set()        # slugs handed out already
SLUG_FOR = {}        # thing  ->  its slug


def slugify(text):
    s = unicodedata.normalize("NFKD", str(text)).encode("ascii", "ignore").decode()
    s = s.replace("'", "").replace("’", "")        # PDF'S -> PDFS, not pdf-s
    s = re.sub(r"[^A-Za-z0-9]+", "-", s).strip("-").lower()
    return s or "item"


def claim(key, names):
    """One tidy slug per thing. names run outermost to innermost, for clashes."""
    if key in SLUG_FOR:
        return SLUG_FOR[key]
    base = slugify(names[-1])
    parents = [slugify(n) for n in names[:-1]]
    slug, n = base, 1
    while slug in TAKEN:
        if parents:
            slug = parents.pop() + "-" + base
        else:
            n += 1
            slug = base + "-" + str(n)
    TAKEN.add(slug)
    SLUG_FOR[key] = slug
    return slug


def short_link(target, names):
    """A slug that only forwards somewhere: a file, or the front page."""
    slug = claim(target, names)
    SHORTS[slug] = target
    return slug


def clear_shorts():
    """Start the /s folder empty so removed cases leave nothing behind."""
    if os.path.isdir(SHORTS_DIR):
        shutil.rmtree(SHORTS_DIR)
    os.makedirs(SHORTS_DIR, exist_ok=True)


def write_shorts():
    """Write the forwarding pages. The real pages are written as they're built."""
    for slug, target in SHORTS.items():
        d = os.path.join(SHORTS_DIR, slug)
        os.makedirs(d, exist_ok=True)
        url = html.escape("../../" + target, quote=True)
        with open(os.path.join(d, "index.html"), "w", encoding="utf-8") as f:
            f.write(REDIRECT.replace("__T__", url))
    print(f"Short addresses: {len(TAKEN)}")


def write_forward(real_dir, slug, depth):
    """Leave a forward at the old long path, so links already shared keep working."""
    url = html.escape("../" * depth + "s/" + slug + "/", quote=True)
    page = (REDIRECT.replace("__T__", url)
            .replace('location.replace("' + url + '");',
                     'location.replace("' + url + '" + location.hash);'))
    save(os.path.join(real_dir, "index.html"), page)


def register_front_links():
    """Tidy addresses for the DSX tables and the gallery images as well.

    Those live on the front page behind a #tables= or #gallery= address, so
    the short page forwards to the front page with that address attached. The
    slug is written back into the json for the page to use.
    """
    for name, key, kind in (("tables.json", "tables", "tables"),
                            ("gallery.json", "images", "gallery")):
        path = os.path.join(ROOT, "assets", name)
        if not os.path.exists(path):
            continue
        try:
            with open(path, encoding="utf-8") as f:
                data = json.load(f)
        except Exception as e:                            # noqa: BLE001
            print(f"  could not read {name}: {e}")
            continue
        items = data.get(key) or []
        for it in items:
            fname = it.get("file")
            if not fname:
                continue
            if kind == "tables":
                label = " ".join(x for x in (it.get("subject") or "",
                                             str(it.get("year") or "")) if x)
            else:
                label = it.get("name") or ""
            label = label.strip() or os.path.splitext(fname)[0]
            target = "#" + kind + "=" + quote(fname)
            it["short"] = "s/" + short_link(target, [kind, label]) + "/"
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=1, ensure_ascii=False)


def share_btn(rel_to_short):
    return (f'<button class="share rshare" type="button" title="Copy link" '
            f'data-share="{rel_to_short}">{SHARE_SVG}</button>')


def scan(abs_dir):
    """One level: (folders, files). Hidden entries and generated pages skipped."""
    folders, files = [], []
    if not os.path.isdir(abs_dir):
        return folders, files
    for n in sorted(os.listdir(abs_dir), key=lambda x: x.lower()):
        if n.startswith("."):
            continue
        full = os.path.join(abs_dir, n)
        if os.path.isdir(full):
            folders.append(n)
        elif os.path.isfile(full):
            if n.lower() in ("readme.md", "index.html"):
                continue
            files.append((n, os.path.getsize(full)))
    return folders, files


def count_items(abs_dir):
    """How many files sit anywhere under this folder."""
    total = 0
    for _root, dirs, names in os.walk(abs_dir):
        dirs[:] = [d for d in dirs if not d.startswith(".")]
        total += len([n for n in names
                      if not n.startswith(".") and n.lower() != "index.html"])
    return total


def folder_row(href, name, abs_sub, share):
    n = count_items(abs_sub)
    return (f'    <li><a href="{href}">'
            f'{FOLDER_SVG}'
            f'<span class="nm">{html.escape(name)}</span>'
            f'<span class="sz">{n} item{"" if n == 1 else "s"}</span>'
            f'<span class="dl">Open</span></a>{share}</li>')


def file_row(href, name, size, share):
    return (f'    <li><a href="{href}" download>'
            f'{DOWNLOAD_SVG}'
            f'<span class="nm">{html.escape(name)}</span>'
            f'<span class="sz">{human_size(size)}</span>'
            f'<span class="dl">Download</span></a>{share}</li>')


def listing(abs_dir, real_dir, delay, gallery=False):
    """Folders first, then files. Pictures become a grid when gallery is on.

    Every page is written at s/<slug>/, so a folder is linked by its own slug
    and a file by its real path two levels up.
    """
    folders, files = scan(abs_dir)
    pics  = [f for f in files if f[0].lower().endswith(IMAGE_EXT)] if gallery else []
    plain = [f for f in files if f not in pics]

    def file_href(name):
        return "../../" + "/".join(quote(p) for p in real_dir) + "/" + quote(name)

    out = []
    if folders or plain:
        out.append(f'  <ul class="files rz" data-rz="{delay}">')
        for d in folders:
            slug = SLUG_FOR["/".join(real_dir + [d]) + "/"]
            out.append(folder_row(f"../{slug}/", d, os.path.join(abs_dir, d),
                                  share_btn(f"../{slug}/")))
        for n, sz in plain:
            slug = SLUG_FOR["/".join(real_dir + [n])]
            out.append(file_row(file_href(n), n, sz, share_btn(f"../{slug}/")))
        out.append("  </ul>")
    if pics:
        out.append(f'  <div class="shots rz" data-rz="{delay + 100}">')
        for n, _sz in pics:
            href = file_href(n)
            out.append(f'    <a href="{href}"><img src="{href}" alt="" loading="lazy"></a>')
        out.append("  </div>")
    return out


def render_page(title, date, blurb, actions, body, up, back_label, back_href,
                og_title="", og_desc="", og_img="", og_url=""):
    att = lambda s: html.escape(s or "", quote=True)
    return (CASE_PAGE
            .replace("__OGTITLE__", att(og_title or title))
            .replace("__OGDESC__", att(og_desc or DEFAULT_DESC))
            .replace("__OGIMG__", att(og_img or SITE + "assets/share.png"))
            .replace("__OGURL__", att(og_url))
            .replace("__TITLE__", html.escape(title))
            .replace("__DATE__", date)
            .replace("__BLURB__", blurb)
            .replace("__ACTIONS__", actions)
            .replace("__BODY__", "\n".join(body))
            .replace('<a class="back" href="__UP__"><svg viewBox="0 0 24 24" aria-hidden="true"><path d="M20 12H4M10 6l-6 6 6 6"/></svg><span>All cases</span></a>',
                     f'<a class="back" href="{back_href}">{BACK_SVG}'
                     f'<span>{html.escape(back_label)}</span></a>')
            .replace("__UP__", up))


def save(target, page):
    os.makedirs(os.path.dirname(target), exist_ok=True)
    old = ""
    if os.path.exists(target):
        with open(target, encoding="utf-8") as f:
            old = f.read()
    if old != page:
        with open(target, "w", encoding="utf-8") as f:
            f.write(page)


def case_share_image(case):
    """The case's own thumbnail for the preview card, or the site banner."""
    thumb = case.get("thumb")
    if thumb:
        return SITE + "/".join(quote(p) for p in thumb.split("/"))
    return SITE + "assets/share.png"


def plan_case(case):
    """Hand out a slug to the case and to everything inside it, before building.

    A row has to know the slug of the folder it points at, so all the slugs
    are decided first and the pages are written afterwards.
    """
    folder = case["folder"]
    abs_folder = os.path.join(ROOT, folder)
    claim(folder + "/", [case["title"]])

    def walk(rel_parts):
        abs_dir = os.path.join(abs_folder, *rel_parts)
        here = [folder] + list(rel_parts)
        names = [case["title"]] + list(rel_parts)
        if len(rel_parts) > 1:                 # Files and Images have no page
            claim("/".join(here) + "/", names)
        folders, files = scan(abs_dir)
        for n, _sz in files:
            # a file has no page of its own, so its slug forwards to the file
            s = claim("/".join(here + [n]), names + [os.path.splitext(n)[0]])
            SHORTS[s] = "/".join(quote(p) for p in here + [n])
        for d in folders:
            walk(rel_parts + [d])

    for sub in ("Files", "Images"):
        if os.path.isdir(os.path.join(abs_folder, sub)):
            walk([sub])


def write_folder_pages(case, rel_parts):
    """This folder's page, then every folder inside it. All of them live in /s."""
    folder = case["folder"]
    abs_folder = os.path.join(ROOT, folder)
    abs_dir = os.path.join(abs_folder, *rel_parts)
    real_dir = [folder] + list(rel_parts)
    name = rel_parts[-1]
    slug = SLUG_FOR["/".join(real_dir) + "/"]

    body = ['  <section class="panel rz" data-rz="320">',
            f'    <div class="sec"><h2>{html.escape(name)}</h2>{share_btn("./")}</div>']
    rendered = listing(abs_dir, real_dir, 520,
                       gallery=(rel_parts[0].lower() == "images"))
    body += rendered if rendered else ['  <p class="blurb">This folder is empty.</p>']
    body.append('  </section>')

    # one level in, back is the case page's own Files or Images section;
    # deeper than that, the parent folder has a page of its own
    if len(rel_parts) > 2:
        back_label = rel_parts[-2]
        back_href = "../" + SLUG_FOR["/".join(real_dir[:-1]) + "/"] + "/"
    else:
        back_label = rel_parts[0]
        back_href = "../" + SLUG_FOR[folder + "/"] + "/#" + rel_parts[0].lower()

    save(os.path.join(SHORTS_DIR, slug, "index.html"),
         render_page(name, "", "", "", body, up="../../",
                     back_label=back_label, back_href=back_href,
                     og_title=f"{name} — {case['title']}",
                     og_desc=case["blurb"] or DEFAULT_DESC,
                     og_img=case_share_image(case),
                     og_url=SITE + "s/" + slug + "/"))
    write_forward(abs_dir, slug, len(real_dir))

    for d in scan(abs_dir)[0]:
        write_folder_pages(case, list(rel_parts) + [d])


def write_case_page(case):
    folder = case["folder"]
    abs_folder = os.path.join(ROOT, folder)
    slug = SLUG_FOR[folder + "/"]

    body = []
    for sub, anchor, head, delay in (("Files", "files", "Files", 1180),
                                     ("Images", "images", "Images", 1640)):
        abs_sub = os.path.join(abs_folder, sub)
        if not os.path.isdir(abs_sub):
            continue
        rendered = listing(abs_sub, [folder, sub], delay + 220,
                           gallery=(sub == "Images"))
        if not rendered:
            continue
        body.append(f'  <section class="panel rz" data-rz="{delay}" id="{anchor}">')
        body.append(f'    <div class="sec"><h2>{head}</h2></div>')
        body += rendered
        body.append('  </section>')

    if not body:
        body.append('  <p class="blurb">No documents published for this case yet.</p>')

    blurb = (f'  <p class="blurb rz" data-rz="640">{html.escape(case["blurb"])}</p>'
             if case["blurb"] else "")

    acts = []
    if case.get("video"):
        acts.append(f'    <a href="{html.escape(case["video"], quote=True)}" '
                    f'target="_blank" rel="noopener">{PLAY_SVG}'
                    f'<span>Watch the video</span></a>')
    if case.get("zip"):
        acts.append(f'    <a class="alt" href="../../{case["zip"]}" download>'
                    f'{ZIP_SVG}<span>Download all</span></a>')
    actions = ('  <div class="top rz" data-rz="900">\n' + "\n".join(acts) + '\n  </div>') if acts else ""
    date = case["date"].strftime("%B %-d, %Y") if case["date"] else ""

    save(os.path.join(SHORTS_DIR, slug, "index.html"),
         render_page(case["title"], date, blurb, actions, body,
                     up="../../", back_label="All cases", back_href="../../",
                     og_title=case["title"],
                     og_desc=case["blurb"] or DEFAULT_DESC,
                     og_img=case_share_image(case),
                     og_url=SITE + "s/" + slug + "/"))
    write_forward(abs_folder, slug, 1)

    for sub in ("Files", "Images"):
        if os.path.isdir(os.path.join(abs_folder, sub)):
            for d in scan(os.path.join(abs_folder, sub))[0]:
                write_folder_pages(case, [sub, d])
    return True


def main():
    with open(INDEX, encoding="utf-8") as f:
        page = f.read()

    cases = collect()
    clear_shorts()
    for c in cases:            # slugs for everything first, then the pages
        plan_case(c)
    for c in cases:
        write_case_page(c)

    start = page.find("<!-- CASES:START")
    end = page.find("<!-- CASES:END -->")
    if start == -1 or end == -1:
        sys.exit("index.html is missing the CASES:START / CASES:END markers.")

    start_line_end = page.index("\n", start) + 1
    new_body = render(cases) + "\n  "
    updated = page[:start_line_end] + new_body + page[end:]

    register_front_links()
    write_shorts()   # last, so every link above is registered first

    if updated == page:
        print("No change.")
        return

    with open(INDEX, "w", encoding="utf-8") as f:
        f.write(updated)
    print("index.html updated.")


if __name__ == "__main__":
    main()
