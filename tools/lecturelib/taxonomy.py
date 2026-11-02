"""Load the subject/topic/rule targets that lecture passages are tagged against.

Two sources are merged:

* a built-in keyword taxonomy (``taxonomies/florida.json``) for Florida Part A, and
* optionally the Ruled study library (``content/subjects/<id>/outline.json``),
  whose topics and rules give much richer text to match against and let a
  lecture moment link straight to a rule card in the app.

The library reader is deliberately tolerant: it looks for ``topics`` lists and
``rules`` lists and gathers every string inside them, so small schema changes
in the library don't break tagging.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

HERE = Path(__file__).resolve().parent
BUILTIN_DIR = HERE / "taxonomies"


@dataclass
class Rule:
    id: str
    title: str
    text: str


@dataclass
class Topic:
    id: str
    subject: str
    title: str
    keywords: list[str] = field(default_factory=list)
    text: str = ""
    rules: list[Rule] = field(default_factory=list)
    source: str = "builtin"  # "builtin" or "library"


@dataclass
class Subject:
    id: str
    title: str
    aliases: list[str] = field(default_factory=list)
    part: str = ""
    rules_subject: str | None = None
    source: str = "builtin"
    topics: list[Topic] = field(default_factory=list)


def _strings(obj, skip_keys=("id", "topic", "subject", "rules", "ruleIds", "weight", "difficulty", "answer", "exams", "authority")):
    """Collect every human-readable string inside a JSON value."""
    out = []
    if isinstance(obj, str):
        out.append(obj)
    elif isinstance(obj, list):
        for x in obj:
            out.extend(_strings(x, skip_keys))
    elif isinstance(obj, dict):
        for k, v in obj.items():
            if k in skip_keys:
                continue
            out.extend(_strings(v, skip_keys))
    return out


def _title_of(obj: dict, fallback: str) -> str:
    for key in ("title", "name", "label", "heading", "short"):
        if isinstance(obj.get(key), str) and obj[key].strip():
            return obj[key].strip()
    tail = fallback.split(".")[-1]
    return tail.replace("-", " ").capitalize()


def load_builtin(name: str = "florida") -> list[Subject]:
    path = BUILTIN_DIR / f"{name}.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    subjects = []
    for s in data["subjects"]:
        subj = Subject(
            id=s["id"],
            title=s["title"],
            aliases=list(s.get("aliases", [])),
            part=s.get("part", ""),
            rules_subject=s.get("rulesSubject"),
        )
        for t in s.get("topics", []):
            subj.topics.append(
                Topic(
                    id=t["id"],
                    subject=subj.id,
                    title=t["title"],
                    keywords=list(t.get("keywords", [])),
                    text=" ".join([t["title"]] + list(t.get("keywords", []))),
                )
            )
        subjects.append(subj)
    return subjects


def find_library_subjects_dir(path: Path) -> Path | None:
    """Accept the app folder, its ``content`` folder or ``content/subjects``."""
    path = Path(path)
    for cand in (path / "content" / "subjects", path / "subjects", path):
        if cand.is_dir() and any(cand.glob("*/outline.json")):
            return cand
    return None


def load_library(path: Path) -> list[Subject]:
    """Read Ruled outlines. Returns [] if the folder has none."""
    subjects_dir = find_library_subjects_dir(path)
    if not subjects_dir:
        return []
    subjects = []
    for outline_path in sorted(subjects_dir.glob("*/outline.json")):
        sid = outline_path.parent.name
        try:
            data = json.loads(outline_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        subj = Subject(id=sid, title=_title_of(data, sid), source="library", rules_subject=sid)
        for t in data.get("topics", []) or []:
            if not isinstance(t, dict) or "id" not in t:
                continue
            tid = str(t["id"])
            topic = Topic(id=tid, subject=sid, title=_title_of(t, tid), source="library")
            for r in t.get("rules", []) or []:
                if isinstance(r, dict) and "id" in r:
                    rid = str(r["id"])
                    rtext = " ".join(_strings(r))
                    topic.rules.append(Rule(id=rid, title=_title_of(r, rid), text=rtext))
            intro = t.get("intro") if isinstance(t.get("intro"), str) else ""
            topic.text = " ".join([topic.title, intro] + [r.text for r in topic.rules])
            subj.topics.append(topic)
        if subj.topics:
            subjects.append(subj)
    return subjects


def load_library_stats(path: Path) -> dict:
    """Per-topic counts of rules, questions and essays in the Ruled library."""
    subjects_dir = find_library_subjects_dir(path)
    stats: dict[str, dict] = {}
    if not subjects_dir:
        return stats
    for sub in sorted(p for p in subjects_dir.iterdir() if p.is_dir()):
        for fname, key, list_key in (("questions.json", "questions", "questions"), ("essays.json", "essays", "essays")):
            f = sub / fname
            if not f.exists():
                continue
            try:
                data = json.loads(f.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                continue
            items = data.get(list_key, data) if isinstance(data, dict) else data
            for item in items if isinstance(items, list) else []:
                if not isinstance(item, dict):
                    continue
                topics = item.get("topic") or item.get("topics") or []
                if isinstance(topics, str):
                    topics = [topics]
                for t in topics:
                    stats.setdefault(str(t), {}).setdefault(key, 0)
                    stats[str(t)][key] += 1
    return stats


def merged(library: Path | None = None, builtin: str | None = "florida") -> list[Subject]:
    subjects: list[Subject] = []
    if builtin:
        subjects.extend(load_builtin(builtin))
    if library:
        subjects.extend(load_library(library))
    return subjects
