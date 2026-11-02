// Pure helpers for the Lecture Library (no DOM), shared by the page and by
// any Ruled section that wants "watch the lecture on this rule" links.
// Tokenising mirrors tools/lecturelib/textutil.py closely enough that the
// same words match on both sides.

const STOP = new Set(`a about above after again against all also am an and any are as at be because been before being
below between both but by can cannot could did do does doing down during each either else even ever every few for from
further get gets getting go goes going gonna got had has have having he her here hers herself him himself his how i if
in into is it its itself just kind know let like look lot lots make many may maybe me might more most much must my
myself need no nor not now of off ok okay on once one only or other ought our ours ourselves out over own pretty really
right said same say says see she should so some something still such sure take than that the their theirs them
themselves then there these they thing things think this those though through thus to too two under until up upon us
very want was way we well went were what when where whether which while who whom why will with would yeah yes yet you
your yours yourself um uh actually basically alright`.split(/\s+/));

const SUFFIXES = [["ies", "y"], ["sses", "ss"], ["ments", "ment"], ["ings", ""], ["ing", ""],
  ["edly", ""], ["ed", ""], ["es", "e"], ["s", ""]];

// Mirrors stem() in tools/lecturelib/textutil.py exactly; change both together.
export function stem(word) {
  if (word.length <= 3 || /^\d+$/.test(word)) return word;
  for (const [suf, rep] of SUFFIXES) {
    if (word.endsWith(suf) && word.length - suf.length >= 3) {
      if (suf === "s" && /(ss|us|is)$/.test(word)) break;
      word = word.slice(0, -suf.length) + rep;
      break;
    }
  }
  if (word.length >= 4 && word.endsWith("e")) word = word.slice(0, -1);
  return word;
}

export function tokenize(text) {
  const words = String(text).toLowerCase().replace(/’/g, "'").match(/[a-z0-9]+(?:'[a-z]+)?/g) || [];
  const out = [];
  for (let w of words) {
    if (w.endsWith("'s")) w = w.slice(0, -2);
    if (w.length < 2 || STOP.has(w)) continue;
    out.push(stem(w));
  }
  return out;
}

export function fmtClock(seconds) {
  const s = Math.max(0, Math.round(Number(seconds) || 0));
  const h = Math.floor(s / 3600), m = Math.floor((s % 3600) / 60), r = s % 60;
  return h ? `${h}:${String(m).padStart(2, "0")}:${String(r).padStart(2, "0")}` : `${m}:${String(r).padStart(2, "0")}`;
}

export function fmtDuration(seconds) {
  const m = Math.round((Number(seconds) || 0) / 60);
  if (m < 60) return `${m} min`;
  return `${Math.floor(m / 60)} h ${String(m % 60).padStart(2, "0")} min`;
}

/** Build an in-memory search index over passages: [{lectureId, chunk, start, text}]. */
export function buildIndex(passages) {
  const postings = new Map();
  passages.forEach((p, i) => {
    const counts = new Map();
    for (const t of tokenize(p.text)) counts.set(t, (counts.get(t) || 0) + 1);
    for (const [t, c] of counts) {
      if (!postings.has(t)) postings.set(t, []);
      postings.get(t).push([i, c]);
    }
  });
  return { passages, postings, n: passages.length };
}

/** Rank passages for a query: TF-IDF over passages plus a bonus for the exact phrase. */
export function search(index, query, { limit = 40, filter } = {}) {
  const qTerms = [...new Set(tokenize(query))];
  if (!qTerms.length) return [];
  const scores = new Map();
  const matched = new Map();
  for (const t of qTerms) {
    const list = index.postings.get(t);
    if (!list) continue;
    const idf = Math.log((1 + index.n) / (1 + list.length)) + 1;
    for (const [i, c] of list) {
      scores.set(i, (scores.get(i) || 0) + (1 + Math.log(c)) * idf);
      matched.set(i, (matched.get(i) || 0) + 1);
    }
  }
  const phrase = normalizePhrase(query);
  const results = [];
  for (const [i, s] of scores) {
    const p = index.passages[i];
    if (filter && !filter(p)) continue;
    let score = s * (matched.get(i) / qTerms.length);
    if (phrase.length > 3 && normalizePhrase(p.text).includes(phrase)) score *= 1.6;
    results.push({ ...p, score });
  }
  results.sort((a, b) => b.score - a.score);
  return results.slice(0, limit);
}

function normalizePhrase(text) {
  return " " + (String(text).toLowerCase().match(/[a-z0-9]+/g) || []).join(" ") + " ";
}

/** Split text into [{text, hit}] runs so query words can be highlighted safely (no innerHTML). */
export function highlightRuns(text, query) {
  const stems = new Set(tokenize(query));
  if (!stems.size) return [{ text, hit: false }];
  const runs = [];
  const re = /[A-Za-z0-9’']+|[^A-Za-z0-9’']+/g;
  let m;
  while ((m = re.exec(text))) {
    const piece = m[0];
    const isWord = /[A-Za-z0-9]/.test(piece);
    const hit = isWord && tokenize(piece).some((t) => stems.has(t));
    const last = runs[runs.length - 1];
    if (last && last.hit === hit) last.text += piece; else runs.push({ text: piece, hit });
  }
  return runs;
}

/** A window of text around the first query hit. */
export function snippet(text, query, width = 260) {
  const stems = tokenize(query);
  const lower = text.toLowerCase();
  let pos = -1;
  for (const s of stems) {
    pos = lower.indexOf(s.slice(0, Math.max(4, s.length - 1)));
    if (pos >= 0) break;
  }
  if (pos < 0) return text.length > width ? text.slice(0, width) + "…" : text;
  let a = Math.max(0, pos - Math.floor(width / 3));
  const sp = text.lastIndexOf(" ", a);
  if (a > 0 && sp > a - 20) a = sp + 1;
  const b = Math.min(text.length, a + width);
  return (a ? "…" : "") + text.slice(a, b) + (b < text.length ? "…" : "");
}

/** Index of the passage playing at time t (passages sorted by start). */
export function passageAt(chunks, t) {
  let lo = 0, hi = chunks.length - 1, ans = -1;
  while (lo <= hi) {
    const mid = (lo + hi) >> 1;
    if (chunks[mid].start <= t) { ans = mid; lo = mid + 1; } else hi = mid - 1;
  }
  return ans;
}

/** Parse "#/lecture/<id>?t=90", "#/search/<q>", "#/topic/<id>", "#/rule/<id>". */
export function parseRoute(hash) {
  const raw = String(hash || "").replace(/^#\/?/, "");
  const [path, qs = ""] = raw.split("?");
  const [kind, ...rest] = path.split("/");
  const id = decodeURIComponent(rest.join("/"));
  const params = new URLSearchParams(qs);
  if (kind === "lecture" && id) return { kind, id, t: params.has("t") ? Number(params.get("t")) || 0 : null };
  if ((kind === "search" || kind === "topic" || kind === "rule") && id) return { kind, id };
  return { kind: "home" };
}

/** Lecture moments for a rule or topic id from links.json (best first). */
export function momentsFor(links, id) {
  if (!links) return [];
  const rows = (links.rules && links.rules[id]) || (links.topics && links.topics[id]) || [];
  return rows.map(([lecture, chunk, start, score]) => ({ lecture, chunk, start, score }));
}
