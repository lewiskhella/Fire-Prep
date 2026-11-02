// Loads the PRIVATE lecture index that tools/lectures.py builds from the
// student's own lecture transcripts (default: <project>/private/lectures/).
// Everything here is optional: with no index the Lectures section explains
// how to build one, and the topic pages simply show no lecture links.

import { buildIndex } from './lectures-core.js';

const BASE = new URL('../../../private/lectures/', import.meta.url);
const PREFS_KEY = 'ruled:lectures:v1';
const cache = new Map();

function getJSON(path) {
  if (cache.has(path)) return cache.get(path);
  const p = fetch(new URL(path, BASE), { cache: 'no-cache' })
    .then(r => (r.ok ? r.json() : null))
    .catch(() => null);
  cache.set(path, p);
  return p;
}

/** The manifest (index.json) or null when no index has been built. */
export function lectureIndex() {
  return getJSON('index.json').then(m => (m && Array.isArray(m.lectures) ? m : null));
}

export function lecture(id) {
  return getJSON(`lectures/${encodeURIComponent(id)}.json`);
}

export function lectureLinks() {
  return getJSON('links.json');
}

let searchIndexPromise = null;
/** Loads every lecture (4 at a time) and builds the passage search index. */
export function lectureSearchIndex(onProgress) {
  if (searchIndexPromise) return searchIndexPromise;
  searchIndexPromise = (async () => {
    const m = await lectureIndex();
    if (!m) return null;
    const passages = [];
    const queue = m.lectures.slice();
    let done = 0;
    async function worker() {
      while (queue.length) {
        const meta = queue.shift();
        const lec = await lecture(meta.id);
        done++;
        onProgress?.(done, m.lectures.length);
        if (!lec) continue;
        for (const ch of lec.chunks) {
          passages.push({ lecture: lec.id, title: lec.title, subject: lec.subject, chunk: ch.i, start: ch.start, text: ch.text, topic: ch.tags[0]?.topic || null });
        }
      }
    }
    await Promise.all([worker(), worker(), worker(), worker()]);
    return buildIndex(passages);
  })();
  return searchIndexPromise;
}

// ---- Per-device preferences (separate from ruled:v1 so the main store's schema is untouched)

function readPrefs() {
  try { return JSON.parse(localStorage.getItem(PREFS_KEY) || '{}') || {}; } catch { return {}; }
}
function writePrefs(p) {
  try { localStorage.setItem(PREFS_KEY, JSON.stringify(p)); } catch { /* storage unavailable */ }
}

export const DEFAULT_MEDIA_BASE = 'http://127.0.0.1:4322/';

export function prefs() {
  const p = readPrefs();
  return { mediaBase: p.mediaBase ?? DEFAULT_MEDIA_BASE, positions: p.positions || {}, rate: p.rate || 1 };
}

export function setPref(key, value) {
  const p = readPrefs();
  p[key] = value;
  writePrefs(p);
}

export function savePosition(lectureId, seconds) {
  const p = readPrefs();
  p.positions = p.positions || {};
  p.positions[lectureId] = Math.round(seconds);
  // Keep the 200 most recent.
  const keys = Object.keys(p.positions);
  if (keys.length > 200) delete p.positions[keys[0]];
  writePrefs(p);
}

/** URL for a lecture's video/audio, or null. */
export function mediaUrl(lec, base = prefs().mediaBase) {
  if (!lec?.media?.path || !base) return null;
  const path = lec.media.path.split('/').map(encodeURIComponent).join('/');
  return base.replace(/\/?$/, '/') + path;
}
