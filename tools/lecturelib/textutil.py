"""Small text helpers: tokenising, light stemming and TF-IDF scoring.

Standard library only, so the tools run with the Mac's stock ``python3``.
"""
from __future__ import annotations

import math
import re
from collections import Counter

_WORD = re.compile(r"[a-z0-9]+(?:'[a-z]+)?")

STOPWORDS = frozenset(
    """
    a about above after again against all also am an and any are aren't as at be because been before being
    below between both but by can can't cannot could couldn't did didn't do does doesn't doing don't down
    during each either else even ever every few for from further get gets getting go goes going gonna got
    gotta had hadn't has hasn't have haven't having he he'd he'll he's her here here's hers herself him
    himself his how how's i i'd i'll i'm i've if in into is isn't it it's its itself just kind know let
    let's like look lot lots make many may maybe me might more most much must mustn't my myself need no
    nor not now of off ok okay on once one only or other ought our ours ourselves out over own pretty
    really right said same say says see she she'd she'll she's should shouldn't so some something still
    such sure take than that that's the their theirs them themselves then there there's these they
    they'd they'll they're they've thing things think this those though through thus to too two under
    until up upon us very want wanna was wasn't way we we'd we'll we're we've well went were weren't
    what what's when when's where where's whether which while who who's whom why why's will with won't
    would wouldn't yeah yes yet you you'd you'll you're you've your yours yourself yourselves um uh
    actually basically gonna alright going also okay so-called got really again
    """.split()
)


def stem(word: str) -> str:
    """A deliberately light suffix stripper (plural/tense), stable enough for matching.

    Mirrored exactly by ``stem`` in app/js/lib/lectures-core.js; change both together.
    """
    if len(word) <= 3 or word.isdigit():
        return word
    for suf, rep in (
        ("ies", "y"),
        ("sses", "ss"),
        ("ments", "ment"),
        ("ings", ""),
        ("ing", ""),
        ("edly", ""),
        ("ed", ""),
        ("es", "e"),
        ("s", ""),
    ):
        if word.endswith(suf) and len(word) - len(suf) >= 3:
            if suf == "s" and word.endswith(("ss", "us", "is")):
                break
            word = word[: -len(suf)] + rep
            break
    if len(word) >= 4 and word.endswith("e"):
        word = word[:-1]  # settle/settled, devise/devised -> one stem
    return word


def tokens(text: str, keep_stopwords: bool = False) -> list[str]:
    words = _WORD.findall(text.lower().replace("’", "'"))
    out = []
    for w in words:
        if w.endswith("'s"):
            w = w[:-2]
        if not keep_stopwords and (w in STOPWORDS or len(w) < 2):
            continue
        out.append(stem(w))
    return out


def ngrams(toks: list[str], n: int) -> list[str]:
    return [" ".join(toks[i : i + n]) for i in range(len(toks) - n + 1)]


def surface_bigrams(text: str) -> list[tuple[str, str]]:
    """(stemmed bigram, as-spoken bigram) pairs, for showing phrases to people."""
    words = [w[:-2] if w.endswith("'s") else w for w in _WORD.findall(text.lower().replace("’", "'"))]
    kept = [w for w in words if w not in STOPWORDS and len(w) >= 2]
    return [(stem(a) + " " + stem(b), a + " " + b) for a, b in zip(kept, kept[1:])]


def terms(text: str) -> list[str]:
    """Unigrams plus bigrams: bigrams capture phrases like 'proposal settlement'."""
    t = tokens(text)
    return t + ngrams(t, 2)


class TfIdf:
    """Fit on a list of documents (each a list of terms); score new text against them."""

    def __init__(self, docs: list[list[str]]):
        self.n = len(docs)
        df: Counter = Counter()
        for d in docs:
            df.update(set(d))
        self.idf = {t: math.log((1 + self.n) / (1 + c)) + 1.0 for t, c in df.items()}
        self.vectors = [self.vector(d) for d in docs]
        self.postings: dict[str, list[tuple[int, float]]] = {}
        for i, v in enumerate(self.vectors):
            for t, w in v.items():
                self.postings.setdefault(t, []).append((i, w))

    def vector(self, doc_terms: list[str]) -> dict[str, float]:
        tf = Counter(doc_terms)
        if not tf:
            return {}
        vec = {t: (1 + math.log(c)) * self.idf.get(t, 0.0) for t, c in tf.items() if t in self.idf}
        norm = math.sqrt(sum(v * v for v in vec.values())) or 1.0
        return {t: v / norm for t, v in vec.items()}

    @staticmethod
    def cosine(a: dict[str, float], b: dict[str, float]) -> float:
        if len(a) > len(b):
            a, b = b, a
        return sum(v * b.get(t, 0.0) for t, v in a.items())

    def rank(self, doc_terms: list[str], top: int = 5) -> list[tuple[int, float]]:
        q = self.vector(doc_terms)
        acc: dict[int, float] = {}
        for t, qw in q.items():
            for i, w in self.postings.get(t, ()):
                acc[i] = acc.get(i, 0.0) + qw * w
        scored = sorted(acc.items(), key=lambda s: -s[1])
        return [s for s in scored if s[1] > 0][:top]


def slugify(text: str, maxlen: int = 60) -> str:
    s = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")
    return s[:maxlen].rstrip("-") or "item"


def fmt_clock(seconds: float) -> str:
    seconds = int(round(seconds))
    h, rem = divmod(seconds, 3600)
    m, s = divmod(rem, 60)
    return f"{h}:{m:02d}:{s:02d}" if h else f"{m}:{s:02d}"
