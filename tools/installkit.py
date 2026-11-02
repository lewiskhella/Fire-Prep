"""Shared machinery for the add-on installers (install_lectures.py, install_florida.py).

An installer is a list of copies (repo path -> app path) and a list of patches.
Every file a run copies over or edits is backed up first to
``<app>/<backup_name>/<timestamp>/``; ``uninstall`` restores the oldest backup
(the state before the first install) and removes what the first install created.
Patches are anchored on a line of existing code and are skipped, with a
warning, when that line has changed, so a run never mangles a file.
"""
from __future__ import annotations

import json
import shutil
import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent


class Patch:
    """Edit one file. ``done_marker`` present -> already applied. ``apply`` returns
    the new text, or None when its anchor is missing."""

    def __init__(self, path: str, done_marker: str | None, describe: str):
        self.path, self.done_marker, self.describe = path, done_marker, describe

    def apply(self, text: str) -> str | None:  # pragma: no cover - overridden
        raise NotImplementedError


class InsertBefore(Patch):
    """Insert ``insert`` as whole lines just before the line containing ``anchor``."""

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
    """Insert ``insert`` as whole lines just after the line containing ``anchor``."""

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


class Replace(Patch):
    """Replace an exact snippet (each ``old`` must occur exactly once)."""

    def __init__(self, path, done_marker, describe, pairs):
        super().__init__(path, done_marker, describe)
        self.pairs = pairs

    def apply(self, text):
        for old, new in self.pairs:
            if text.count(old) != 1:
                return None
            text = text.replace(old, new)
        return text


class JsonEdit(Patch):
    """Edit a JSON file with a function (data -> data). Unchanged output means done."""

    def __init__(self, path, describe, fn):
        super().__init__(path, None, describe)
        self.fn = fn

    def apply(self, text):
        try:
            data = json.loads(text)
        except json.JSONDecodeError:
            return None
        out = self.fn(data)
        return json.dumps(out, ensure_ascii=False, indent=2) + "\n"


def _backup(app: Path, rel: str, stamp_dir: Path):
    src = app / rel
    if not src.exists():
        return
    dst = stamp_dir / rel
    if dst.exists():
        return  # keep the first (pre-run) copy
    dst.parent.mkdir(parents=True, exist_ok=True)
    if src.is_dir():
        shutil.copytree(src, dst, dirs_exist_ok=True)
    else:
        shutil.copy2(src, dst)


def _new_stamp_dir(app: Path, backup_name: str) -> Path:
    stamp = time.strftime("%Y%m%d-%H%M%S")
    stamp_dir = app / backup_name / stamp
    n = 1
    while stamp_dir.exists():  # never mix two runs' backups
        n += 1
        stamp_dir = app / backup_name / f"{stamp}-{n:02d}"
    return stamp_dir


def install(app: Path, dry: bool, copies: list[tuple[str, str]], patches: list[Patch], backup_name: str) -> int:
    """Returns 0 when everything applied (or was already applied), 1 when something was skipped."""
    stamp_dir = _new_stamp_dir(app, backup_name)
    warnings = 0
    created = []

    for src_rel, dst_rel in copies:
        src, dst = REPO / src_rel, app / dst_rel
        if not src.exists():
            print(f"  SKIPPED     {dst_rel}: {src_rel} not found in this repo")
            warnings += 1
            continue
        if not dst.exists():
            created.append(dst_rel)
        if dry:
            print(f"  would copy  {dst_rel}")
            continue
        _backup(app, dst_rel, stamp_dir)
        if src.is_dir():
            shutil.copytree(src, dst, dirs_exist_ok=True, ignore=shutil.ignore_patterns("__pycache__", "*.pyc", "._*"))
        else:
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, dst)
        print(f"  copied      {dst_rel}")

    for p in patches:
        target = app / p.path
        if not target.exists():
            print(f"  SKIPPED     {p.path}: file not found ({p.describe})")
            warnings += 1
            continue
        text = target.read_text(encoding="utf-8")
        if p.done_marker and p.done_marker in text:
            print(f"  unchanged   {p.path}: already has {p.describe}")
            continue
        new = p.apply(text)
        if new is None:
            print(f"  SKIPPED     {p.path}: anchor not found; add {p.describe} by hand")
            warnings += 1
            continue
        if new == text:
            print(f"  unchanged   {p.path}: already has {p.describe}")
            continue
        if dry:
            print(f"  would edit  {p.path}: {p.describe}")
            continue
        _backup(app, p.path, stamp_dir)
        target.write_text(new, encoding="utf-8")
        print(f"  edited      {p.path}: {p.describe}")

    if not dry:
        stamp_dir.mkdir(parents=True, exist_ok=True)
        (stamp_dir / "CREATED.txt").write_text("".join(c + "\n" for c in created), encoding="utf-8")
        print(f"\nBackup: {stamp_dir}")
    return 1 if warnings else 0


def uninstall(app: Path, dry: bool, backup_name: str) -> int:
    root = app / backup_name
    stamps = sorted(p for p in root.iterdir() if p.is_dir()) if root.exists() else []
    if not stamps:
        sys.exit("no backup found; nothing to undo")
    stamp_dir = stamps[0]  # the first install holds the original files
    created_file = stamp_dir / "CREATED.txt"
    created = [l for l in created_file.read_text(encoding="utf-8").splitlines() if l] if created_file.exists() else []
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
    print("Restored the files from before the first install.")
    return 0


def check_target(app: Path, needed: list[str]):
    missing = [p for p in needed if not (app / p).exists()]
    if missing:
        sys.exit(f"{app} doesn't look like the Ruled app folder (missing: {', '.join(missing)})")
