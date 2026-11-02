#!/usr/bin/env python3
"""Install the Lectures section (§ 11) and transcript tools into the Ruled app.

    python3 tools/install_lectures.py "/Volumes/Extreme Pro/Bar Prep App"
    python3 tools/install_lectures.py "/Volumes/Extreme Pro/Bar Prep App" --dry-run
    python3 tools/install_lectures.py "/Volumes/Extreme Pro/Bar Prep App" --uninstall

What it does (every changed file is backed up to <app>/.lectures-backup/<time>/):
  * copies the new files (views/lectures.js, lib/lectures*.js, ui/lecture-links.js,
    css/lectures.css, tools/lectures.py, tools/lecturelib/)
  * main.js      adds the #/lectures and #/lectures/:id routes
  * shell.js     adds "§11 Lectures" to the navigation
  * index.html   links css/lectures.css
  * topic.js     shows an "On tape" box (best lecture moments) on each outline topic
  * .gitignore   ignores private/ (the lecture index holds lecture wording)

Each edit is anchored on a line of the existing code and is skipped, with a
warning, if that line has changed, so it is safe to run while the app is
evolving and safe to run twice.
"""
from __future__ import annotations

import argparse
import shutil
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parent

FILES = [
    "app/js/lib/lectures.js",
    "app/js/lib/lectures-core.js",
    "app/js/views/lectures.js",
    "app/js/ui/lecture-links.js",
    "app/css/lectures.css",
    "tools/lectures.py",
]
PACKAGE = "tools/lecturelib"

ROUTES = "route('/lectures', () => import('./views/lectures.js'));\nroute('/lectures/:id', () => import('./views/lectures.js'));\n"
NAV_ITEM = "  { sec: '11', path: '/lectures', label: 'Lectures', icon: 'play' },\n"
CSS_LINK = '  <link rel="stylesheet" href="css/lectures.css">\n'
TOPIC_IMPORT = "import { lectureAside } from '../ui/lecture-links.js';\n"


class Patch:
    def __init__(self, path: str, done_marker: str, describe: str):
        self.path, self.done_marker, self.describe = path, done_marker, describe

    def apply(self, text: str) -> str | None:  # pragma: no cover - overridden
        raise NotImplementedError


class InsertBefore(Patch):
    def __init__(self, path, done_marker, describe, anchor, insert):
        super().__init__(path, done_marker, describe)
        self.anchor, self.insert = anchor, insert

    def apply(self, text):
        i = text.find(self.anchor)
        if i < 0:
            return None
        line_start = text.rfind("\n", 0, i) + 1
        return text[:line_start] + self.insert + text[line_start:]


class InsertAfterLine(Patch):
    def __init__(self, path, done_marker, describe, anchor, insert):
        super().__init__(path, done_marker, describe)
        self.anchor, self.insert = anchor, insert

    def apply(self, text):
        i = text.find(self.anchor)
        if i < 0:
            return None
        line_end = text.find("\n", i)
        line_end = len(text) if line_end < 0 else line_end + 1
        return text[:line_end] + self.insert + text[line_end:]


class TopicAside(Patch):
    """Import lectureAside and place it just before the topic's rule list."""

    def apply(self, text):
        anchor_import = "from '../ui/rule.js';"
        anchor_list = "rules.length ? list : emptyState("
        if anchor_import not in text or anchor_list not in text:
            return None
        text = InsertAfterLine(self.path, "", "", anchor_import, TOPIC_IMPORT).apply(text)
        i = text.find(anchor_list)
        line_start = text.rfind("\n", 0, i) + 1
        indent = text[line_start:i]
        if indent.strip():
            indent = " " * (len(indent) - len(indent.lstrip()))
            return text[:i] + "lectureAside(t),\n" + indent + text[i:]
        return text[:line_start] + indent + "lectureAside(t),\n" + text[line_start:]


PATCHES = [
    InsertBefore("app/js/main.js", "'/lectures'", "routes #/lectures and #/lectures/:id", "route('*'", ROUTES),
    InsertAfterLine("app/js/ui/shell.js", "path: '/lectures'", "navigation entry §11 Lectures", "path: '/guide'", NAV_ITEM),
    InsertAfterLine("app/index.html", "css/lectures.css", "stylesheet link", 'href="css/views.css"', CSS_LINK),
    TopicAside("app/js/views/topic.js", "lectureAside", "\"On tape\" box on outline topics"),
]


def check_target(app: Path):
    needed = ["app/js/main.js", "app/index.html", "app/js/ui/shell.js", "app/js/lib/dom.js", "app/js/ui/kit.js", "app/js/lib/content.js"]
    missing = [p for p in needed if not (app / p).exists()]
    if missing:
        sys.exit(f"{app} doesn't look like the Ruled app folder (missing: {', '.join(missing)})")


def backup(app: Path, rel: str, stamp_dir: Path, dry: bool):
    src = app / rel
    if not src.exists():
        return
    dst = stamp_dir / rel
    if not dry:
        dst.parent.mkdir(parents=True, exist_ok=True)
        if src.is_dir():
            shutil.copytree(src, dst, dirs_exist_ok=True)
        else:
            shutil.copy2(src, dst)


def install(app: Path, dry: bool) -> int:
    check_target(app)
    stamp = time.strftime("%Y%m%d-%H%M%S")
    stamp_dir = app / ".lectures-backup" / stamp
    n = 1
    while stamp_dir.exists():  # never mix two runs' backups
        n += 1
        stamp_dir = app / ".lectures-backup" / f"{stamp}-{n:02d}"
    warnings = 0
    created = []

    for rel in FILES + [PACKAGE]:
        src, dst = REPO / rel, app / rel
        existed = dst.exists()
        backup(app, rel, stamp_dir, dry)
        if not existed:
            created.append(rel)
        if dry:
            print(f"  would copy  {rel}")
            continue
        if src.is_dir():
            shutil.copytree(src, dst, dirs_exist_ok=True, ignore=shutil.ignore_patterns("__pycache__", "*.pyc", "._*"))
        else:
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, dst)
        print(f"  copied      {rel}")

    for p in PATCHES:
        target = app / p.path
        if not target.exists():
            print(f"  SKIPPED     {p.path}: file not found ({p.describe})")
            warnings += 1
            continue
        text = target.read_text(encoding="utf-8")
        if p.done_marker in text:
            print(f"  unchanged   {p.path}: already has {p.describe}")
            continue
        new = p.apply(text)
        if new is None:
            print(f"  SKIPPED     {p.path}: anchor line not found; add {p.describe} by hand (see INTEGRATION.md)")
            warnings += 1
            continue
        if dry:
            print(f"  would edit  {p.path}: {p.describe}")
            continue
        backup(app, p.path, stamp_dir, dry)
        target.write_text(new, encoding="utf-8")
        print(f"  edited      {p.path}: {p.describe}")

    gi = app / ".gitignore"
    if not gi.exists() or "private/" not in gi.read_text(encoding="utf-8"):
        if dry:
            print("  would add   private/ to .gitignore")
        else:
            backup(app, ".gitignore", stamp_dir, dry)
            with open(gi, "a", encoding="utf-8") as f:
                f.write("\n# Private lecture index built from your own transcripts (tools/lectures.py)\nprivate/\n")
            print("  edited      .gitignore: private/")

    if not dry:
        stamp_dir.mkdir(parents=True, exist_ok=True)
        (stamp_dir / "CREATED.txt").write_text("\n".join(created) + ("\n" if created else ""), encoding="utf-8")
        print(f"\nBackup: {stamp_dir}")
    print("\nNext: build the index, then open http://localhost:4321/app/#/lectures")
    print('  python3 tools/lectures.py build --transcripts "/path/to/Florida Bar videos" --library . --out private/lectures')
    return 1 if warnings else 0


def uninstall(app: Path, dry: bool) -> int:
    root = app / ".lectures-backup"
    stamps = sorted(p for p in root.iterdir() if p.is_dir()) if root.exists() else []
    if not stamps:
        sys.exit("no backup found; nothing to undo")
    stamp_dir = stamps[0]  # the first install holds the original files
    created = (stamp_dir / "CREATED.txt").read_text(encoding="utf-8").split() if (stamp_dir / "CREATED.txt").exists() else []
    for f in sorted(stamp_dir.rglob("*")):
        if f.is_file() and f.name != "CREATED.txt":
            rel = f.relative_to(stamp_dir)
            print(f"  restore     {rel}")
            if not dry:
                (app / rel).parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(f, app / rel)
    for rel in created:
        target = app / rel
        print(f"  remove      {rel}")
        if not dry and target.exists():
            shutil.rmtree(target) if target.is_dir() else target.unlink()
    print("Restored the files from the first install's backup. private/ (your lecture index) was left alone.")
    return 0


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("app", help="the Ruled app folder, e.g. '/Volumes/Extreme Pro/Bar Prep App'")
    ap.add_argument("--dry-run", action="store_true", help="show what would change")
    ap.add_argument("--uninstall", action="store_true", help="restore the files backed up by the first install")
    args = ap.parse_args(argv)
    app = Path(args.app).expanduser().resolve()
    if not app.is_dir():
        sys.exit(f"not a folder: {app}")
    return uninstall(app, args.dry_run) if args.uninstall else install(app, args.dry_run)


if __name__ == "__main__":
    sys.exit(main())
