"""Turn a folder of lecture transcripts into a tagged, searchable lecture index.

Flow: discover transcripts -> parse to timed segments -> group into ~75 s
passages ("chunks") -> tag each chunk with the subjects/topics/rules it
discusses -> write ``index.json``, one file per lecture, and ``links.json``
(topic/rule id -> lecture moments) for the app.

"""
from __future__ import annotations

import hashlib
import json
import re
import time
from collections import Counter, defaultdict
from dataclasses import dataclass
from pathlib import Path

from . import formats, textutil
from .taxonomy import Subject, Topic

SCHEMA_VERSION = 1
# Bump when tagging, chunking or tokenising changes so cached lectures are redone.
PIPELINE_VERSION = 3
TARGET_CHUNK_SECONDS = 75.0
MAX_CHUNK_SECONDS = 150.0
MIN_TOPIC_SCORE = 0.12
MIN_RULE_SCORE = 0.16
_SENTENCE_END = re.compile(r"[.!?][\"')\]]?$")
_SENTENCES = re.compile(r"(?<=[.!?])\s+(?=[A-Za-z\"'(])")
# Phrases lecturers use when they flag exam material.
_TIP_CUES = [
    (re.compile(r"\b(on|for) (the|your) (bar |florida )?exam\b", re.I), 3),
    (re.compile(r"\b(bar )?examiners?\b", re.I), 3),
    (re.compile(r"\b(heavily |frequently |always |often )?tested\b", re.I), 2),
    (re.compile(r"\b(trap|tricky|trick question|red flag|common mistake|gotcha)\b", re.I), 3),
    (re.compile(r"\b(favou?rite|loves? to|love to test)\b", re.I), 2),
    (re.compile(r"\b(memori[sz]e|remember|don'?t forget|do not forget|never forget)\b", re.I), 2),
    (re.compile(r"\b(watch out|be careful|make sure|key (point|thing|word|issue)|important|critical)\b", re.I), 1),
    (re.compile(r"\b(the rule is|the test is|elements are|black ?letter)\b", re.I), 2),
    (re.compile(r"\b(always|never)\b", re.I), 1),
]


def exam_tips(text: str, limit: int = 2) -> list[str]:
    """Sentences where the lecturer flags exam material, strongest first."""
    scored = []
    for sent in _SENTENCES.split(text):
        n = len(sent.split())
        if n < 6 or n > 70:
            continue
        score = sum(w for rx, w in _TIP_CUES if rx.search(sent))
        if score >= 2:
            scored.append((score, sent.strip()))
    scored.sort(key=lambda x: -x[0])
    return [t for _, t in scored[:limit]]


# ---------------------------------------------------------------- discovery

def discover(root: Path) -> list[Path]:
    """Every transcript under ``root``. When one lecture has several formats,
    prefer the richest (json > vtt > srt > tsv > txt > md)."""
    root = Path(root)
    rank = {".json": 0, ".vtt": 1, ".srt": 2, ".tsv": 3, ".txt": 4, ".md": 5}
    best: dict[Path, Path] = {}
    for p in sorted(root.rglob("*")):
        if not p.is_file() or p.suffix.lower() not in rank:
            continue
        if any(part.startswith(".") for part in p.relative_to(root).parts):
            continue
        if p.name.lower() in ("readme.md", "readme.txt", "index.json", "links.json") or p.name.endswith(".lectures.json"):
            continue
        key = p.with_suffix("")
        if key not in best or rank[p.suffix.lower()] < rank[best[key].suffix.lower()]:
            best[key] = p
    return sorted(best.values())


def find_media(transcript: Path, transcripts_root: Path, media_root: Path | None) -> Path | None:
    """A video/audio file with the same name, next to the transcript or at the
    mirrored path under ``media_root``."""
    candidates_dirs = [transcript.parent]
    if media_root:
        rel = transcript.parent.relative_to(transcripts_root)
        candidates_dirs.append(Path(media_root) / rel)
    for d in candidates_dirs:
        for ext in formats.MEDIA_EXTS:
            for cand in (d / (transcript.stem + ext), d / (transcript.stem + ext.upper())):
                if cand.exists():
                    return cand
    return None


def title_from_path(rel: Path) -> str:
    stem = rel.stem
    if " " not in stem:  # slug-style names: hearsay-part-1, wills_intestacy
        stem = re.sub(r"[-_.]+", " ", stem)
    stem = re.sub(r"[_]+", " ", stem)
    stem = re.sub(r"\s*[-–]\s*", " – ", stem)
    stem = re.sub(r"\s+", " ", stem).strip(" –")
    if stem.islower() or stem.isupper():
        stem = stem.title()
    return stem or rel.stem


def lecture_id(rel: Path) -> str:
    base = textutil.slugify(str(rel.with_suffix("")), 70)
    digest = hashlib.sha1(str(rel.with_suffix("")).encode("utf-8")).hexdigest()[:6]
    return f"{base}-{digest}"


# ----------------------------------------------------------------- chunking

def chunk_segments(segs: list[dict], target: float = TARGET_CHUNK_SECONDS, maximum: float = MAX_CHUNK_SECONDS) -> list[dict]:
    """Group caption-sized segments into passages of roughly ``target`` seconds,
    preferring to break at the end of a sentence."""
    chunks: list[dict] = []
    cur: list[dict] = []

    def flush():
        if cur:
            chunks.append({"start": cur[0]["start"], "end": max(s["end"] for s in cur), "text": " ".join(s["text"] for s in cur)})
            cur.clear()

    for seg in segs:
        cur.append(seg)
        dur = cur[-1]["end"] - cur[0]["start"]
        if dur >= maximum or (dur >= target and _SENTENCE_END.search(seg["text"])):
            flush()
    flush()
    # Fold a short tail into the previous passage.
    if len(chunks) >= 2 and chunks[-1]["end"] - chunks[-1]["start"] < target / 3:
        tail = chunks.pop()
        chunks[-1]["end"] = tail["end"]
        chunks[-1]["text"] += " " + tail["text"]
    return chunks


# ------------------------------------------------------------------ tagging

@dataclass
class _Target:
    topic: Topic
    subject: Subject
    phrases: list[str]


def _norm_phrase(s: str) -> str:
    return " " + " ".join(textutil.tokens(s, keep_stopwords=True)) + " "


class Tagger:
    """Scores passages against topics (TF-IDF cosine plus exact keyword-phrase
    hits) and, inside the best topics, against individual rules."""

    def __init__(self, subjects: list[Subject]):
        self.subjects = {s.id: s for s in subjects}
        self.targets: list[_Target] = []
        for s in subjects:
            for t in s.topics:
                phrases = [_norm_phrase(k) for k in t.keywords if len(k) >= 3]
                self.targets.append(_Target(t, s, [p for p in phrases if p.strip()]))
        docs = [textutil.terms(t.topic.text + " " + t.subject.title) for t in self.targets]
        self.topic_model = textutil.TfIdf(docs) if docs else None
        self.rule_index: list[tuple[str, str, str]] = []  # (rule id, topic id, subject id)
        rule_docs = []
        for t in self.targets:
            for r in t.topic.rules:
                self.rule_index.append((r.id, t.topic.id, t.subject.id))
                rule_docs.append(textutil.terms(r.text))
        self.rule_model = textutil.TfIdf(rule_docs) if rule_docs else None
        self._alias = []
        for s in subjects:
            for a in [s.title] + s.aliases:
                self._alias.append((_norm_phrase(a), s.id))

    def tag(self, text: str, top: int = 3) -> tuple[list[dict], list[dict]]:
        if not self.topic_model:
            return [], []
        t_terms = textutil.terms(text)
        norm = _norm_phrase(text)
        scores: dict[int, float] = {}
        for idx, cos in self.topic_model.rank(t_terms, top=12):
            scores[idx] = cos
        for idx, tgt in enumerate(self.targets):
            hits = sum(1 for p in tgt.phrases if p in norm)
            if hits:
                scores[idx] = scores.get(idx, 0.0) + 0.07 * min(hits, 5)
        ranked = sorted(scores.items(), key=lambda kv: -kv[1])
        tags = []
        for idx, score in ranked:
            if score < MIN_TOPIC_SCORE or len(tags) >= top:
                break
            tgt = self.targets[idx]
            tags.append({"subject": tgt.subject.id, "topic": tgt.topic.id, "score": round(score, 3)})
        rules = []
        if self.rule_model and tags:
            wanted = {t["topic"] for t in tags}
            for ridx, score in self.rule_model.rank(t_terms, top=25):
                rid, tid, sid = self.rule_index[ridx]
                if tid in wanted and score >= MIN_RULE_SCORE:
                    rules.append({"rule": rid, "topic": tid, "score": round(score, 3)})
                if len(rules) >= 3:
                    break
        return tags, rules

    def twins(self, subject_id: str) -> list[str]:
        """Subjects covering the same law in the other taxonomy (fl-evidence <-> evidence)."""
        s = self.subjects.get(subject_id)
        if not s:
            return []
        if s.source == "library":
            return [o.id for o in self.subjects.values() if o.source != "library" and o.rules_subject == subject_id]
        return [s.rules_subject] if s.rules_subject in self.subjects else []

    def guess_subject_from_name(self, rel: Path) -> str | None:
        name = _norm_phrase(" ".join(rel.with_suffix("").parts))
        best, best_len = None, 0
        for phrase, sid in self._alias:
            if phrase in name and len(phrase) > best_len:
                best, best_len = sid, len(phrase)
        return best


# -------------------------------------------------------------------- build

def _sha1(path: Path) -> str:
    h = hashlib.sha1()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def _signature(subjects: list[Subject]) -> str:
    h = hashlib.sha1(f"pipeline-{PIPELINE_VERSION}".encode())
    for s in subjects:
        for t in s.topics:
            h.update(t.id.encode())
            h.update(t.text.encode("utf-8", "ignore"))
    return h.hexdigest()[:12]


def process_lecture(path: Path, root: Path, tagger: Tagger, media_root: Path | None = None) -> dict:
    rel = path.relative_to(root)
    segs, timing, fmt = formats.read_transcript(path)
    chunks = chunk_segments(segs)
    secs_by_subject: Counter = Counter()
    secs_by_topic: Counter = Counter()
    out_chunks = []
    for i, ch in enumerate(chunks):
        tags, rules = tagger.tag(ch["text"])
        dur = max(0.0, ch["end"] - ch["start"])
        if tags:
            secs_by_subject[tags[0]["subject"]] += dur
            secs_by_topic[tags[0]["topic"]] += dur
        out_chunks.append(
            {
                "i": i,
                "start": round(ch["start"], 2),
                "end": round(ch["end"], 2),
                "text": ch["text"],
                "tags": tags,
                "rules": rules,
                "tips": exam_tips(ch["text"]),
            }
        )
    named = tagger.guess_subject_from_name(rel)
    by_content = secs_by_subject.most_common(1)[0][0] if secs_by_subject else None
    if named:
        # A folder called "Evidence" could mean the Florida code or the federal
        # rules: when both exist, let the lecture's own content decide.
        twins = tagger.twins(named)
        if twins:
            named = max([named] + twins, key=lambda sid: secs_by_subject.get(sid, 0.0))
    subject = named or by_content
    media = find_media(path, root, media_root)
    duration = round(max((c["end"] for c in chunks), default=0.0), 2)
    words = sum(len(c["text"].split()) for c in chunks)
    return {
        "schema": SCHEMA_VERSION,
        "id": lecture_id(rel),
        "title": title_from_path(rel),
        "folder": rel.parent.as_posix() if str(rel.parent) != "." else "",
        "subject": subject,
        "subjectSource": "name" if named else ("content" if by_content else None),
        "duration": duration,
        "timing": timing,
        "words": words,
        "source": {"path": rel.as_posix(), "format": fmt, "sha1": _sha1(path)},
        "media": _media_ref(media, root, media_root),
        "topTopics": [{"topic": t, "seconds": round(s, 1)} for t, s in secs_by_topic.most_common(8)],
        "chunks": out_chunks,
    }


def _media_ref(media: Path | None, root: Path, media_root: Path | None) -> dict | None:
    """Where the player finds the video: relative to the media root (served by
    ``lectures.py serve-media``) or, failing that, to the transcripts folder."""
    if not media:
        return None
    if media_root and _is_under(media, media_root):
        return {"root": "media", "path": media.resolve().relative_to(Path(media_root).resolve()).as_posix()}
    if _is_under(media, root):
        return {"root": "transcripts", "path": media.resolve().relative_to(Path(root).resolve()).as_posix()}
    return {"root": "unknown", "path": media.name}


def _is_under(p: Path, root: Path | None) -> bool:
    if root is None:
        return False
    try:
        p.resolve().relative_to(Path(root).resolve())
        return True
    except ValueError:
        return False


def build(transcripts: Path, out: Path, subjects: list[Subject], media_root: Path | None = None, log=print) -> dict:
    """Build (or incrementally refresh) the lecture index in ``out``.

    A lecture is reprocessed only when its transcript changed or the taxonomy
    changed, so this is cheap to re-run while transcription is still going.
    """
    transcripts, out = Path(transcripts), Path(out)
    (out / "lectures").mkdir(parents=True, exist_ok=True)
    tagger = Tagger(subjects)
    sig = _signature(subjects)
    manifest_path = out / "index.json"
    old = {}
    if manifest_path.exists():
        try:
            prev = json.loads(manifest_path.read_text(encoding="utf-8"))
            if prev.get("taxonomySignature") == sig:
                old = {l["source"]["path"]: l for l in prev.get("lectures", [])}
        except (OSError, json.JSONDecodeError, KeyError):
            old = {}

    found = discover(transcripts)
    entries, errors, reused, fresh = [], [], 0, 0
    keep_files = set()
    for path in found:
        rel = path.relative_to(transcripts).as_posix()
        prev = old.get(rel)
        lec_file = out / "lectures" / f"{lecture_id(Path(rel))}.json"
        try:
            if prev and lec_file.exists() and prev["source"].get("sha1") == _sha1(path):
                lec = json.loads(lec_file.read_text(encoding="utf-8"))
                reused += 1
            else:
                lec = process_lecture(path, transcripts, tagger, media_root)
                lec_file.write_text(json.dumps(lec, ensure_ascii=False, indent=1), encoding="utf-8")
                fresh += 1
        except Exception as exc:  # one bad file must never stop the whole build
            errors.append({"path": rel, "error": f"{type(exc).__name__}: {exc}"})
            continue
        if not lec["chunks"]:
            errors.append({"path": rel, "error": "no text"})
            continue
        keep_files.add(lec_file.name)
        entries.append({k: v for k, v in lec.items() if k != "chunks"} | {"chunks": len(lec["chunks"])})

    for stale in (out / "lectures").glob("*.json"):
        if stale.name not in keep_files:
            stale.unlink()

    entries.sort(key=lambda l: (l["subject"] or "~", l["folder"], l["title"]))
    subj_meta = []
    for s in subjects:
        n = sum(1 for e in entries if e["subject"] == s.id)
        subj_meta.append({"id": s.id, "title": s.title, "source": s.source, "part": s.part, "rulesSubject": s.rules_subject, "lectures": n,
                          "topics": [{"id": t.id, "title": t.title} for t in s.topics]})
    manifest = {
        "schema": SCHEMA_VERSION,
        "generated": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "taxonomySignature": sig,
        "totals": {
            "lectures": len(entries),
            "seconds": round(sum(e["duration"] for e in entries), 1),
            "words": sum(e["words"] for e in entries),
        },
        "subjects": subj_meta,
        "lectures": entries,
        "errors": errors,
    }
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=1), encoding="utf-8")
    links = build_links(out, entries)
    (out / "links.json").write_text(json.dumps(links, ensure_ascii=False, indent=1), encoding="utf-8")
    log(f"lectures: {len(entries)} indexed ({fresh} processed, {reused} unchanged), {len(errors)} skipped")
    return manifest


def build_links(out: Path, entries: list[dict], per_target: int = 8) -> dict:
    """topic id / rule id -> best lecture moments, for 'Watch the lecture' links."""
    topics: dict[str, list] = defaultdict(list)
    rules: dict[str, list] = defaultdict(list)
    tips: dict[str, list] = defaultdict(list)
    for e in entries:
        lec = json.loads((out / "lectures" / f"{e['id']}.json").read_text(encoding="utf-8"))
        for ch in lec["chunks"]:
            for tag in ch["tags"][:1]:
                topics[tag["topic"]].append([e["id"], ch["i"], ch["start"], tag["score"]])
            for r in ch["rules"]:
                rules[r["rule"]].append([e["id"], ch["i"], ch["start"], r["score"]])
            if ch.get("tips") and ch["tags"]:
                for tip in ch["tips"]:
                    tips[ch["tags"][0]["topic"]].append([e["id"], ch["i"], ch["start"], tip])

    def best(moments):
        # One moment per lecture (its best), then the strongest lectures first.
        per_lecture = {}
        for m in moments:
            if m[0] not in per_lecture or m[3] > per_lecture[m[0]][3]:
                per_lecture[m[0]] = m
        return sorted(per_lecture.values(), key=lambda m: -m[3])[:per_target]

    return {
        "schema": SCHEMA_VERSION,
        "fields": ["lecture", "chunk", "start", "score"],
        "topics": {k: best(v) for k, v in sorted(topics.items())},
        "rules": {k: best(v) for k, v in sorted(rules.items())},
        "tipFields": ["lecture", "chunk", "start", "text"],
        "tips": {k: v[:12] for k, v in sorted(tips.items())},
    }


# --------------------------------------------------------- reading the index

def load_index(out: Path) -> tuple[dict, dict[str, dict]]:
    out = Path(out)
    manifest = json.loads((out / "index.json").read_text(encoding="utf-8"))
    lectures = {}
    for e in manifest["lectures"]:
        lectures[e["id"]] = json.loads((out / "lectures" / f"{e['id']}.json").read_text(encoding="utf-8"))
    return manifest, lectures


def search(out: Path, query: str, limit: int = 10, subject: str | None = None) -> list[dict]:
    manifest, lectures = load_index(out)
    docs, refs = [], []
    for lid, lec in lectures.items():
        if subject and lec["subject"] != subject:
            continue
        for ch in lec["chunks"]:
            docs.append(textutil.terms(ch["text"]))
            refs.append((lid, ch))
    if not docs:
        return []
    model = textutil.TfIdf(docs)
    q_terms = textutil.terms(query)
    phrase = _norm_phrase(query)
    results = []
    for idx, score in model.rank(q_terms, top=limit * 4):
        lid, ch = refs[idx]
        if phrase.strip() and phrase in _norm_phrase(ch["text"]):
            score += 0.25
        results.append({"lecture": lid, "title": lectures[lid]["title"], "chunk": ch["i"], "start": ch["start"], "score": round(score, 3), "text": ch["text"]})
    results.sort(key=lambda r: -r["score"])
    return results[:limit]


def snippet(text: str, query: str, width: int = 220) -> str:
    q = [w for w in textutil.tokens(query)]
    low = text.lower()
    pos = -1
    for w in q:
        pos = low.find(w[: max(4, len(w) - 1)])
        if pos >= 0:
            break
    if pos < 0:
        return text[:width] + ("…" if len(text) > width else "")
    a = max(0, pos - width // 3)
    b = min(len(text), a + width)
    return ("…" if a else "") + text[a:b] + ("…" if b < len(text) else "")


# ----------------------------------------------------------------- coverage

def coverage(out: Path, subjects: list[Subject], library_stats: dict | None = None, library_text: str = "") -> str:
    """Markdown report: what the lectures emphasise vs. what the library holds."""
    manifest, lectures = load_index(out)
    library_stats = library_stats or {}
    secs_topic: Counter = Counter()
    secs_subject: Counter = Counter()
    untagged = 0.0
    subject_terms: dict[str, Counter] = defaultdict(Counter)
    spoken: dict[str, Counter] = defaultdict(Counter)
    for lec in lectures.values():
        for ch in lec["chunks"]:
            dur = ch["end"] - ch["start"]
            if ch["tags"]:
                secs_topic[ch["tags"][0]["topic"]] += dur
                secs_subject[ch["tags"][0]["subject"]] += dur
                for stemmed, surface in textutil.surface_bigrams(ch["text"]):
                    subject_terms[ch["tags"][0]["subject"]][stemmed] += 1
                    spoken[stemmed][surface] += 1
            else:
                untagged += dur
    total = sum(secs_subject.values()) + untagged
    lines = ["# Lecture coverage report", ""]
    lines.append(f"Generated {manifest['generated']} from {manifest['totals']['lectures']} lectures "
                 f"({total / 3600:.1f} hours). Untagged: {untagged / 60:.0f} min.")
    lines.append("")
    lines.append("Minutes are lecture time whose best tag is that topic. 'Rules', 'Qs' and 'Essays' are what the Ruled library already holds for the topic (blank when the topic is Florida-only and has no library equivalent yet).")
    lines.append("")
    lib_words = set(textutil.terms(library_text)) if library_text else set()
    quiet = []
    for s in subjects:
        smin = secs_subject.get(s.id, 0) / 60
        if smin == 0:
            if s.source != "library":
                quiet.append(f"{s.title} (`{s.id}`)")
            continue
        lines.append(f"## {s.title} (`{s.id}`) — {smin:.0f} min")
        lines.append("")
        lines.append("| Topic | Lecture min | Rules | Qs | Essays | Note |")
        lines.append("|---|---:|---:|---:|---:|---|")
        for t in sorted(s.topics, key=lambda t: -secs_topic.get(t.id, 0)):
            mins = secs_topic.get(t.id, 0) / 60
            st = library_stats.get(t.id, {})
            nrules = len(t.rules) if t.rules else ""
            note = ""
            if mins >= 10 and not t.rules and not st:
                note = "**gap: lectured, no library content**"
            elif mins == 0 and (t.rules or st):
                note = "not lectured"
            lines.append(f"| {t.title} | {mins:.0f} | {nrules} | {st.get('questions', '')} | {st.get('essays', '')} | {note} |")
        if lib_words and subject_terms.get(s.id):
            missing = [(term, c) for term, c in subject_terms[s.id].most_common(400) if term not in lib_words and c >= 3][:15]
            if missing:
                lines.append("")
                shown = ", ".join(f"*{spoken[t].most_common(1)[0][0]}* ({c})" for t, c in missing)
                lines.append("Phrases the lectures repeat that appear nowhere in the library: " + shown)
        lines.append("")
    if quiet:
        lines.append("## Not in the lectures yet")
        lines.append("")
        lines.extend(f"- {q}" for q in quiet)
        lines.append("")
    if manifest.get("errors"):
        lines.append("## Skipped files")
        lines.append("")
        for e in manifest["errors"]:
            lines.append(f"- `{e['path']}`: {e['error']}")
    return "\n".join(lines) + "\n"


# ------------------------------------------------------------ authoring aid

def briefs(out: Path, subjects: list[Subject], subject_id: str, per_topic: int = 12) -> str:
    """A markdown authoring brief for one subject: for each topic, where the
    lectures discuss it (timestamps) and the recurring terms. Authors write
    ORIGINAL rules/questions from primary sources; the brief only says what to
    cover and where to re-listen."""
    manifest, lectures = load_index(out)
    subj = next((s for s in subjects if s.id == subject_id), None)
    if not subj:
        raise SystemExit(f"unknown subject {subject_id}")
    moments: dict[str, list] = defaultdict(list)
    terms_by_topic: dict[str, Counter] = defaultdict(Counter)
    for lec in lectures.values():
        for ch in lec["chunks"]:
            for tag in ch["tags"][:1]:
                if tag["subject"] == subject_id:
                    moments[tag["topic"]].append((tag["score"], lec, ch))
                    terms_by_topic[tag["topic"]].update(surface for _, surface in textutil.surface_bigrams(ch["text"]))
    lines = [f"# Authoring brief — {subj.title}", "",
             "What the lectures cover for this subject, topic by topic: how much time each gets, the terms they keep using, "
             "and the best passages to re-listen to. Use it to plan and write the subject's rules, questions and essays.", ""]
    for t in subj.topics:
        ms = sorted(moments.get(t.id, []), key=lambda m: -m[0])[:per_topic]
        mins = sum(ch["end"] - ch["start"] for _, _, ch in moments.get(t.id, [])) / 60
        lines.append(f"## {t.title} (`{t.id}`) — {mins:.0f} min of lecture")
        common = [term for term, c in terms_by_topic[t.id].most_common(25) if c >= 2][:12]
        if common:
            lines.append("")
            lines.append("Recurring terms: " + ", ".join(common))
        if ms:
            lines.append("")
            for score, lec, ch in ms:
                lines.append(f"- {lec['title']} @ {textutil.fmt_clock(ch['start'])} (score {score})")
        else:
            lines.append("")
            lines.append("- Not found in the lectures yet.")
        lines.append("")
    return "\n".join(lines) + "\n"


def export_corpus(out: Path, dest: Path) -> int:
    """Plain-text copy of every lecture, for the originality checker's
    reference corpus (so new content can be checked against lecture wording)."""
    manifest, lectures = load_index(out)
    dest = Path(dest)
    dest.mkdir(parents=True, exist_ok=True)
    for lid, lec in lectures.items():
        body = "\n\n".join(ch["text"] for ch in lec["chunks"])
        (dest / f"{lid}.txt").write_text(f"{lec['title']}\n\n{body}\n", encoding="utf-8")
    return len(lectures)
