#!/usr/bin/env python3
"""Puts loose files dropped at the repo root into the folder they belong in.

Upload anything to the repo root. This runs before the site is built and
moves whatever it recognises:

  build_cases.py        -> tools/
  sort_files.py         -> tools/
  build-cases.yml       -> .github/workflows/
  any loose image       -> assets/

Left where they are:
  index.html            the site's front page belongs at the root
  README.md             the repo's own readme
  a folder              that is a case, and cases live at the root

Anything else loose at the root is left alone rather than guessed at.
"""

import os
import shutil

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# Folders that are part of the site, not cases. Never touched.
SYSTEM_DIRS = {".git", ".github", "tools", "assets", "_inbox"}

# Files that belong at the root. Never moved.
ROOT_FILES = {"index.html", "readme.md", "channel.txt", ".gitignore",
              ".nojekyll", "cname"}

FILE_RULES = {
    "build_cases.py": "tools",
    "sort_files.py": "tools",
    "sort_inbox.py": "tools",
    "fetch_videos.py": "tools",
}

# GitHub refuses to let an Action write to .github/workflows, so the workflow
# file is never moved. Upload it straight to that folder when it changes.
NEVER_MOVE = {"build-cases.yml"}

IMAGE_EXT = (".jpg", ".jpeg", ".png", ".webp", ".gif", ".avif", ".svg", ".ico")


def destination(name):
    """Folder this file belongs in, or None to leave it where it is."""
    low = name.lower()
    if low in ROOT_FILES or low in NEVER_MOVE:
        return None
    if low in FILE_RULES:
        return FILE_RULES[low]
    if low.endswith(IMAGE_EXT):
        return "assets"
    return None


def move(name, dest_dir):
    src = os.path.join(ROOT, name)
    target_dir = os.path.join(ROOT, dest_dir)
    os.makedirs(target_dir, exist_ok=True)
    target = os.path.join(target_dir, name)
    if os.path.exists(target):
        os.remove(target)
    shutil.move(src, target)
    print(f"  {name}  ->  {dest_dir}/{name}")


def drain_inbox():
    """Backwards compatible: empty _inbox if it still exists."""
    inbox = os.path.join(ROOT, "_inbox")
    if not os.path.isdir(inbox):
        return
    for name in sorted(os.listdir(inbox)):
        if name.startswith(".") or name.lower() == "readme.md":
            continue
        src = os.path.join(inbox, name)
        dest = os.path.join(ROOT, name)
        if os.path.isdir(src):
            if os.path.isdir(dest):
                shutil.rmtree(dest)
        elif os.path.exists(dest):
            os.remove(dest)
        shutil.move(src, dest)
        print(f"  _inbox/{name}  ->  {name}")


def main():
    drain_inbox()

    moved = 0
    for name in sorted(os.listdir(ROOT)):
        path = os.path.join(ROOT, name)
        if os.path.isdir(path):
            continue                      # folders are cases, leave them
        if name.startswith("."):
            continue
        dest = destination(name)
        if dest:
            if moved == 0:
                print("Filing loose files:")
            move(name, dest)
            moved += 1

    if moved == 0:
        print("Nothing to file.")
    else:
        print("Done.")


if __name__ == "__main__":
    main()
