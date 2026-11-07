#!/usr/bin/env python3
"""Saves the channel's latest videos to assets/videos.json.

Reads the channel handle from channel.txt at the repo root (e.g. @vesperdigital),
resolves it to a channel id, then reads the public RSS feed, which carries the
15 most recent uploads. No API key.

If anything fails, the existing videos.json is left alone so the site never
loses its list because of a bad network day.
"""

import json
import os
import re
import sys
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, "assets", "videos.json")
HANDLE_FILE = os.path.join(ROOT, "channel.txt")

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/125.0 Safari/537.36")


def get(url):
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=30) as r:
        return r.read().decode("utf-8", "replace")


def read_handle():
    try:
        with open(HANDLE_FILE, encoding="utf-8") as f:
            h = f.read().strip()
    except OSError:
        h = ""
    return h or "@vesperdigital"


def channel_id(handle):
    if handle.startswith("UC") and len(handle) > 20:
        return handle
    page = get(f"https://www.youtube.com/{handle.lstrip('/')}")
    for pat in (r'"channelId":"(UC[A-Za-z0-9_-]{20,})"',
                r'"externalId":"(UC[A-Za-z0-9_-]{20,})"',
                r'channel/(UC[A-Za-z0-9_-]{20,})'):
        m = re.search(pat, page)
        if m:
            return m.group(1)
    raise RuntimeError("could not find the channel id on that page")


def entries(cid):
    xml = get("https://www.youtube.com/feeds/videos.xml?channel_id=" + cid)
    out = []
    for block in xml.split("<entry>")[1:]:
        vid = re.search(r"<yt:videoId>([^<]+)</yt:videoId>", block)
        title = re.search(r"<title>(.*?)</title>", block, re.S)
        when = re.search(r"<published>([^<]+)</published>", block)
        if not vid:
            continue
        t = (title.group(1) if title else "").strip()
        for a, b in (("&amp;", "&"), ("&lt;", "<"), ("&gt;", ">"),
                     ("&quot;", '"'), ("&#39;", "'")):
            t = t.replace(a, b)
        out.append({
            "id": vid.group(1),
            "title": t,
            "date": (when.group(1)[:10] if when else ""),
        })
    return out


def main():
    handle = read_handle()
    try:
        cid = channel_id(handle)
        vids = entries(cid)
    except Exception as e:                      # noqa: BLE001
        print(f"Could not refresh the video list ({e}). Keeping the old one.")
        return

    if not vids:
        print("Feed returned no videos. Keeping the old list.")
        return

    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    new = json.dumps({"channel": handle, "videos": vids},
                     indent=1, ensure_ascii=False)
    old = ""
    if os.path.exists(OUT):
        with open(OUT, encoding="utf-8") as f:
            old = f.read()
    if new != old:
        with open(OUT, "w", encoding="utf-8") as f:
            f.write(new)
        print(f"Saved {len(vids)} videos for {handle}.")
    else:
        print("Video list unchanged.")


if __name__ == "__main__":
    sys.exit(main())
