#!/usr/bin/env python3
"""Empties _inbox/ by moving everything it holds to where it belongs.

Drop anything into _inbox/ and this works out the destination:

  index.html            -> repo root
  build_cases.py        -> tools/
  sort_inbox.py         -> tools/
  build-cases.yml       -> .github/workflows/
  banner.* / logo.*     -> assets/
  any other loose file  -> assets/
  a folder              -> repo root, treated as a case folder

Existing files are overwritten. _inbox/ is left empty with its README intact.
"""

import os
import shutil
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
INBOX = os.path.join(ROOT, "_inbox")

KEEP = {"readme.md", ".gitkeep"}

FILE_RULES = {
    "index.html": "",
    "build_cases.py": "tools",
    "sort_inbox.py": "tools",
    "build-cases.yml": ".github/workflows",
}

ASSET_STEMS = {"banner", "logo", "favicon", "og", "social"}


def destination(name):
    low = name.lower()
    if low in FILE_RULES:
        return FILE_RULES[low]
    stem = os.path.splitext(low)[0]
    if stem in ASSET_STEMS:
        return "assets"
    return "assets"


def move(src, dest_dir, name):
    target_dir = os.path.join(ROOT, dest_dir) if dest_dir else ROOT
    os.makedirs(target_dir, exist_ok=True)
    target = os.path.join(target_dir, name)
    if os.path.isdir(src):
        if os.path.isdir(target):
            shutil.rmtree(target)
        shutil.move(src, target)
    else:
        if os.path.exists(target):
            os.remove(target)
        shutil.move(src, target)
    shown = os.path.join(dest_dir, name) if dest_dir else name
    print(f"  {name}  ->  {shown}")


def main():
    if not os.path.isdir(INBOX):
        print("No _inbox folder. Nothing to do.")
        return

    entries = [n for n in sorted(os.listdir(INBOX))
               if n.lower() not in KEEP and not n.startswith(".")]
    if not entries:
        print("_inbox is empty. Nothing to do.")
        return

    print(f"Sorting {len(entries)} item(s) out of _inbox:")
    for name in entries:
        src = os.path.join(INBOX, name)
        if os.path.isdir(src):
            move(src, "", name)          # a folder is a case folder
        else:
            move(src, destination(name), name)
    print("Done.")


if __name__ == "__main__":
    main()
