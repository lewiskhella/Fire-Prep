"""Parsers that turn transcript files into a list of timed segments.

Every parser returns ``(segments, timing)`` where ``segments`` is a list of
``{"start": float, "end": float, "text": str}`` dicts (seconds) and ``timing``
is ``"exact"`` when the file carried timestamps or ``"estimated"`` when they
were inferred from word counts.

Supported inputs
----------------
* ``.srt``  SubRip captions
* ``.vtt``  WebVTT captions
* ``.json`` OpenAI-Whisper / mlx-whisper / faster-whisper (``segments``),
            whisper.cpp ``-oj`` (``transcription``), or ``{"text": ...}``
* ``.tsv``  whisper ``start<TAB>end<TAB>text`` in milliseconds
* ``.txt`` / ``.md``  plain text, optionally with ``[hh:mm:ss]`` or
            ``hh:mm:ss`` line prefixes

Only the Python standard library is used.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

TRANSCRIPT_EXTS = (".srt", ".vtt", ".json", ".tsv", ".txt", ".md")
MEDIA_EXTS = (".mp4", ".m4v", ".mov", ".mkv", ".webm", ".mp3", ".m4a", ".wav", ".aac")

# Words per second used when a transcript has no timestamps (about 150 wpm,
# a typical lecture pace).
WORDS_PER_SECOND = 2.5

_TS = r"(?:(\d+):)?(\d{1,2}):(\d{2})(?:[.,](\d{1,3}))?"
_CUE = re.compile(rf"^\s*{_TS}\s*-->\s*{_TS}")
_TXT_STAMP = re.compile(rf"^\s*[\[(]?\s*{_TS}\s*[\])]?\s*[-–:]?\s*(.*)$")
_TAG = re.compile(r"<[^>]+>")
_SPACE = re.compile(r"\s+")


class TranscriptError(ValueError):
    """Raised when a file cannot be read as a transcript."""


def _secs(h, m, s, frac) -> float:
    total = int(h or 0) * 3600 + int(m) * 60 + int(s)
    if frac:
        total += int(frac.ljust(3, "0")[:3]) / 1000.0
    return float(total)


def parse_timestamp(text: str) -> float:
    """Parse ``01:02:03,450`` / ``02:03.4`` / ``1:02:03`` into seconds."""
    m = re.fullmatch(r"\s*" + _TS + r"\s*", text)
    if not m:
        raise TranscriptError(f"not a timestamp: {text!r}")
    return _secs(*m.groups())


def clean_text(text: str) -> str:
    text = _TAG.sub("", text)
    text = text.replace("&nbsp;", " ").replace("&amp;", "&").replace("&lt;", "<").replace("&gt;", ">")
    return _SPACE.sub(" ", text).strip()


def _cue_blocks(raw: str):
    """Yield ``(start, end, text)`` for each cue in SRT or VTT text."""
    lines = raw.replace("\r\n", "\n").replace("\r", "\n").split("\n")
    i, n = 0, len(lines)
    while i < n:
        m = _CUE.match(lines[i])
        if not m:
            i += 1
            continue
        g = m.groups()
        start, end = _secs(*g[0:4]), _secs(*g[4:8])
        i += 1
        body = []
        while i < n and lines[i].strip() and not _CUE.match(lines[i]):
            body.append(lines[i])
            i += 1
        # Drop a trailing SRT sequence number that belongs to the next cue.
        if body and body[-1].strip().isdigit() and i < n and _CUE.match(lines[i] if i < n else ""):
            body.pop()
        yield start, end, clean_text(" ".join(body))


def parse_srt(raw: str):
    return _dedupe_rolling([{"start": s, "end": e, "text": t} for s, e, t in _cue_blocks(raw) if t]), "exact"


def parse_vtt(raw: str):
    # NOTE blocks and STYLE blocks never contain "-->", so _cue_blocks skips them.
    return _dedupe_rolling([{"start": s, "end": e, "text": t} for s, e, t in _cue_blocks(raw) if t]), "exact"


def _dedupe_rolling(segs):
    """Collapse YouTube-style rolling captions where each cue repeats the last.

    Auto-generated captions often show line N, then lines N and N+1, then
    N+1 and N+2. Keeping only the new words avoids indexing everything twice.
    """
    out = []
    for seg in segs:
        if out:
            prev = out[-1]["text"]
            if seg["text"] == prev:
                out[-1]["end"] = max(out[-1]["end"], seg["end"])
                continue
            if seg["text"].startswith(prev) and len(prev) > 0:
                rest = seg["text"][len(prev):].strip()
                if not rest:
                    continue
                seg = dict(seg, text=rest)
            else:
                # Overlap where the previous cue's tail starts this cue.
                pw, sw = prev.split(), seg["text"].split()
                k = min(len(pw), len(sw))
                while k > 0 and pw[-k:] != sw[:k]:
                    k -= 1
                if k >= 3:
                    rest = " ".join(sw[k:])
                    if not rest:
                        continue
                    seg = dict(seg, text=rest)
        out.append(seg)
    return out


def parse_json(raw: str):
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise TranscriptError(f"invalid JSON: {exc}") from exc
    if isinstance(data, dict) and isinstance(data.get("segments"), list):
        segs = []
        for s in data["segments"]:
            text = clean_text(str(s.get("text", "")))
            if text:
                segs.append({"start": float(s.get("start", 0.0)), "end": float(s.get("end", s.get("start", 0.0))), "text": text})
        return segs, "exact"
    if isinstance(data, dict) and isinstance(data.get("transcription"), list):  # whisper.cpp -oj
        segs = []
        for s in data["transcription"]:
            text = clean_text(str(s.get("text", "")))
            if not text:
                continue
            off = s.get("offsets") or {}
            if "from" in off:
                start, end = off["from"] / 1000.0, off.get("to", off["from"]) / 1000.0
            else:
                ts = s.get("timestamps") or {}
                start, end = parse_timestamp(ts.get("from", "0:00")), parse_timestamp(ts.get("to", "0:00"))
            segs.append({"start": start, "end": end, "text": text})
        return segs, "exact"
    if isinstance(data, list) and data and isinstance(data[0], dict) and "text" in data[0]:
        return parse_json(json.dumps({"segments": data}))
    if isinstance(data, dict) and isinstance(data.get("text"), str):
        return parse_txt(data["text"])
    raise TranscriptError("JSON has no 'segments', 'transcription' or 'text' field")


def parse_tsv(raw: str):
    segs = []
    for line in raw.splitlines():
        parts = line.split("\t")
        if len(parts) < 3 or not parts[0].strip().lstrip("-").isdigit():
            continue  # header row or junk
        text = clean_text("\t".join(parts[2:]))
        if text:
            segs.append({"start": int(parts[0]) / 1000.0, "end": int(parts[1]) / 1000.0, "text": text})
    return segs, "exact"


def parse_txt(raw: str):
    """Plain text. Lines that start with a timestamp set the clock."""
    raw = raw.replace("\r\n", "\n").replace("\r", "\n")
    stamped = []
    for line in raw.split("\n"):
        m = _TXT_STAMP.match(line)
        if m:
            text = clean_text(m.group(5))
            stamped.append((_secs(*m.groups()[0:4]), text))
        elif stamped and line.strip():
            t, text = stamped[-1]
            stamped[-1] = (t, (text + " " + clean_text(line)).strip())
    stamped = [(t, x) for t, x in stamped if x]
    if len(stamped) >= 2 and all(stamped[i][0] <= stamped[i + 1][0] for i in range(len(stamped) - 1)):
        segs = []
        for i, (t, text) in enumerate(stamped):
            end = stamped[i + 1][0] if i + 1 < len(stamped) else t + len(text.split()) / WORDS_PER_SECOND
            segs.append({"start": t, "end": end, "text": text})
        return segs, "exact"
    # No usable timestamps: split into paragraphs/sentences and estimate time.
    paras = [clean_text(p) for p in re.split(r"\n\s*\n", raw)]
    pieces = []
    for p in paras:
        if not p:
            continue
        if len(p.split()) > 80:
            pieces.extend(s for s in re.split(r"(?<=[.!?])\s+", p) if s)
        else:
            pieces.append(p)
    segs, clock = [], 0.0
    for text in pieces:
        dur = max(1.0, len(text.split()) / WORDS_PER_SECOND)
        segs.append({"start": round(clock, 2), "end": round(clock + dur, 2), "text": text})
        clock += dur
    return segs, "estimated"


PARSERS = {
    ".srt": parse_srt,
    ".vtt": parse_vtt,
    ".json": parse_json,
    ".tsv": parse_tsv,
    ".txt": parse_txt,
    ".md": parse_txt,
}


def read_transcript(path: Path):
    """Return ``(segments, timing, format)`` for a transcript file."""
    path = Path(path)
    ext = path.suffix.lower()
    if ext not in PARSERS:
        raise TranscriptError(f"unsupported transcript type: {ext}")
    raw = path.read_bytes()
    for enc in ("utf-8-sig", "utf-16", "cp1252", "latin-1"):
        try:
            text = raw.decode(enc)
            break
        except UnicodeDecodeError:
            continue
    segs, timing = PARSERS[ext](text)
    segs = [s for s in segs if s["text"]]
    segs.sort(key=lambda s: s["start"])
    return segs, timing, ext.lstrip(".")
