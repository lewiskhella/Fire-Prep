// § 11 Lectures — the student's own lecture transcripts, indexed by topic.
//   #/lectures                    library: search every transcript, browse by subject
//   #/lectures?topic=<id>         every lecture moment on a topic (or ?rule=<id>)
//   #/lectures/<lectureId>?t=90   read a lecture passage by passage; play from any passage
//
// Data comes from tools/lectures.py (content/lectures/).

import { h, swap, debounce, plural } from '../lib/dom.js';
import { catalog } from '../lib/content.js';
import { page, header, emptyState, backLink } from '../ui/kit.js';
import { icon } from '../ui/icons.js';
import {
  lectureIndex, lecture, lectureLinks, lectureSearchIndex, prefs, setPref, savePosition, mediaUrl, DEFAULT_MEDIA_BASE,
} from '../lib/lectures.js';
import { fmtClock, fmtDuration, search, highlightRuns, snippet, passageAt, momentsFor } from '../lib/lectures-core.js';

export const title = params => (params && params.id ? 'Lecture' : 'Lectures');

export async function render(params, query) {
  const index = await lectureIndex();
  if (!index) return setupView();
  const names = await nameBook(index);
  if (params.id) return readerView(params.id, query, index, names);
  if (query.topic || query.rule) return momentsView(query.rule || query.topic, !!query.rule, index, names);
  return libraryView(query, index, names);
}

// ------------------------------------------------------------------ helpers

async function nameBook(index) {
  const cat = await catalog();
  const subjects = new Map();
  const topics = new Map();
  for (const s of index.subjects || []) {
    subjects.set(s.id, { id: s.id, name: s.title, short: s.title, tab: null, library: s.source === 'library', part: s.part });
    for (const t of s.topics || []) topics.set(t.id, { id: t.id, title: t.title, subject: s.id });
  }
  for (const s of cat.subjects || []) {
    const prev = subjects.get(s.id) || {};
    subjects.set(s.id, { ...prev, id: s.id, name: s.name, short: s.short || s.name, tab: s.tab, library: true });
  }
  return {
    subject: id => subjects.get(id) || { id, name: id ? id.replace(/^fl-/, 'Florida ').replace(/-/g, ' ') : 'Unsorted', short: id || 'Unsorted', tab: null },
    topic: id => topics.get(id) || { id, title: String(id || '').split('.').pop().replace(/-/g, ' '), subject: String(id || '').split('.')[0] },
    subjects,
  };
}

function topicHref(topicId, names) {
  const t = names.topic(topicId);
  const s = names.subject(t.subject);
  // Library topics open the outline; Florida-only topics list their lecture moments.
  return s.library && !String(t.subject).startsWith('fl-')
    ? `#/outlines/${encodeURIComponent(t.subject)}/${encodeURIComponent(topicId)}`
    : `#/lectures?topic=${encodeURIComponent(topicId)}`;
}

function ruleHref(rule) {
  const subjectId = String(rule.topic).split('.')[0];
  return `#/outlines/${encodeURIComponent(subjectId)}/${encodeURIComponent(rule.topic)}?rule=${encodeURIComponent(rule.rule)}`;
}

function marked(text, query) {
  return highlightRuns(text, query).map(r => (r.hit ? h('mark', r.text) : r.text));
}

function withTips(text, tips) {
  if (!tips || !tips.length) return [text];
  const out = [];
  let rest = text;
  for (const tip of tips) {
    const i = rest.indexOf(tip);
    if (i < 0) continue;
    out.push(rest.slice(0, i), h('mark.lec-tip', { title: 'Flagged by the lecturer' }, tip));
    rest = rest.slice(i + tip.length);
  }
  out.push(rest);
  return out;
}

function subjectDot(meta) {
  return h('span.tab-dot', { style: meta.tab ? { '--tab': meta.tab } : null });
}

// -------------------------------------------------------------------- setup

function setupView() {
  return page('narrow lectures-page',
    header({ sec: '11', kicker: 'Lecture library', title: 'Lectures', lede: 'Search and replay your own bar-review lectures, matched to the outline topic each passage covers.' }),
    emptyState('No lecture index yet.',
      'Build one from your transcripts (.srt, .vtt, Whisper .json, .tsv or .txt). Run this from the app folder, then reload:',
      h('div.lec-setup',
        h('pre.lec-cmd', 'python3 tools/lectures.py build \\\n  --transcripts "/path/to/Florida Bar videos" \\\n  --library .'),
        h('p.muted', 'Re-run it as more lectures finish transcribing; unchanged files are skipped. Add --watch 600 to refresh every 10 minutes.'))));
}

// ------------------------------------------------------------------ library

function libraryView(query, index, names) {
  const totals = index.totals || {};
  const bySubject = new Map();
  for (const l of index.lectures) {
    const key = l.subject || '';
    if (!bySubject.has(key)) bySubject.set(key, []);
    bySubject.get(key).push(l);
  }
  const order = [...bySubject.keys()].sort((a, b) => (a === '') - (b === '') || names.subject(a).name.localeCompare(names.subject(b).name));
  let filter = query.subject || '';

  const results = h('section.lec-results', { 'aria-live': 'polite' });
  const listWrap = h('div.lec-shelves');
  const input = h('input.lec-search', {
    type: 'search', placeholder: 'Search every transcript — e.g. “proposal for settlement”', 'aria-label': 'Search lecture transcripts',
    value: query.q || '', autocomplete: 'off', spellcheck: 'false',
  });

  const chips = h('div.chips.lec-filter', { role: 'group', 'aria-label': 'Filter by subject' },
    [['', 'All']].concat(order.map(id => [id, names.subject(id).short])).map(([id, label]) =>
      h('button.chip', {
        type: 'button', 'aria-pressed': String(filter === id), dataset: { subject: id },
        onclick: () => { filter = id; for (const c of chips.children) c.setAttribute('aria-pressed', String(c.dataset.subject === filter)); paintShelves(); runSearch(); },
      }, id ? subjectDot(names.subject(id)) : null, label, h('span.muted.num', ` ${id ? bySubject.get(id).length : index.lectures.length}`))));

  function paintShelves() {
    swap(listWrap, order.filter(id => !filter || id === filter).map(id => {
      const meta = names.subject(id);
      const lectures = bySubject.get(id);
      const secs = lectures.reduce((a, l) => a + (l.duration || 0), 0);
      return h('section.lec-shelf', { style: meta.tab ? { '--tab': meta.tab } : null },
        h('h2.lec-shelf-head', subjectDot(meta), h('span', meta.name), h('span.muted.num', `${plural(lectures.length, 'lecture')} · ${fmtDuration(secs)}`)),
        h('ol.lec-list', lectures.map(l => h('li',
          h('a.lec-card', { href: `#/lectures/${encodeURIComponent(l.id)}` },
            h('span.lec-card-title', l.title),
            h('span.lec-card-meta.num', fmtDuration(l.duration), l.timing === 'estimated' ? ' · timing estimated' : '', l.media ? '' : ' · transcript only'),
            l.topTopics?.length ? h('span.lec-card-topics', l.topTopics.slice(0, 3).map(t => names.topic(t.topic).title).join(' · ')) : null)))));
    }));
  }

  let lastQ = null;
  const runSearch = debounce(async () => {
    const q = input.value.trim();
    history.replaceState(null, '', '#/lectures' + (q ? `?q=${encodeURIComponent(q)}` : ''));
    if (!q) { lastQ = null; swap(results); listWrap.hidden = false; return; }
    lastQ = q;
    listWrap.hidden = true;
    swap(results, h('p.muted', 'Indexing lectures…'));
    const idx = await lectureSearchIndex((done, total) => {
      if (lastQ === q) swap(results, h('p.muted.num', `Indexing lectures… ${done} / ${total}`));
    });
    if (lastQ !== q) return;
    const hits = search(idx, q, { limit: 40, filter: filter ? p => p.subject === filter : null });
    swap(results,
      h('h2.lec-results-head', hits.length ? `${plural(hits.length, 'passage')} for “${q}”` : `Nothing in the lectures for “${q}”.`),
      h('ol.lec-hits', hits.map(hit => h('li.lec-hit',
        h('a', { href: `#/lectures/${encodeURIComponent(hit.lecture)}?t=${Math.floor(hit.start)}` },
          h('span.lec-hit-where', h('span', hit.title), h('time.num', fmtClock(hit.start)), hit.topic ? h('span.muted', names.topic(hit.topic).title) : null),
          h('span.lec-hit-text', marked(snippet(hit.text, q), q)))))));
  }, 180);
  input.addEventListener('input', runSearch);

  paintShelves();
  if (query.q) runSearch();

  return page('lectures-page',
    header({
      sec: '11', kicker: 'Lecture library', title: 'Lectures',
      lede: 'Every lecture is cut into short passages and matched to the outline topic it teaches. Search them all, or open one and play it from any passage.',
      aside: h('dl.lec-totals',
        h('div', h('dt.smallcaps', 'Lectures'), h('dd.num', totals.lectures ?? index.lectures.length)),
        h('div', h('dt.smallcaps', 'Hours'), h('dd.num', ((totals.seconds || 0) / 3600).toFixed(1))),
        h('div', h('dt.smallcaps', 'Updated'), h('dd.num', String(index.generated || '').slice(5, 16).replace('T', ' ')))),
    }),
    h('div.lec-searchbar', icon('search'), input),
    chips,
    results,
    listWrap,
    index.errors?.length ? h('p.muted.lec-skipped', `${plural(index.errors.length, 'transcript')} could not be read; see content/lectures/index.json.`) : null,
    h('p.muted.lec-fine', 'Rebuild with tools/lectures.py build as more lectures are transcribed.'));
}

// ------------------------------------------------------------------ moments

async function momentsView(id, isRule, index, names) {
  const links = await lectureLinks();
  const moments = momentsFor(links, id);
  const t = isRule ? null : names.topic(id);
  const label = isRule ? id.split('.').pop().replace(/-/g, ' ') : t.title;
  const byId = new Map(index.lectures.map(l => [l.id, l]));
  const tips = (!isRule && links?.tips?.[id]) || [];
  const rows = await Promise.all(moments.map(async m => {
    const lec = await lecture(m.lecture);
    const ch = lec?.chunks?.[m.chunk];
    return { m, meta: byId.get(m.lecture), text: ch?.text || '' };
  }));
  return page('narrow lectures-page',
    h('div.crumbs', backLink('#/lectures', 'Lectures')),
    header({ sec: '11', kicker: isRule ? 'Rule on tape' : `Topic on tape · ${names.subject(t.subject).name}`, title: label,
      lede: rows.length ? `${plural(rows.length, 'lecture')} discuss this. Each link starts the lecture at the passage.` : null }),
    rows.length
      ? h('ol.lec-hits', rows.filter(r => r.meta).map(({ m, meta, text }) => h('li.lec-hit',
          h('a', { href: `#/lectures/${encodeURIComponent(m.lecture)}?t=${Math.floor(m.start)}` },
            h('span.lec-hit-where', h('span', meta.title), h('time.num', fmtClock(m.start))),
            h('span.lec-hit-text', snippet(text, label, 300))))))
      : emptyState('No lecture passages matched this yet.', 'They appear as more transcripts are indexed.'),
    tips.length ? h('section.lec-tipbox',
      h('h2.smallcaps', icon('star'), 'What the lecturers flag'),
      h('ol', tips.filter(([lid]) => byId.has(lid)).map(([lid, , start, text]) => h('li',
        h('a', { href: `#/lectures/${encodeURIComponent(lid)}?t=${Math.floor(start)}` },
          h('q', text), h('span.muted', ` — ${byId.get(lid).title}, `), h('time.num', fmtClock(start))))))) : null,
    !isRule && !String(t.subject).startsWith('fl-')
      ? h('p', h('a.btn.ghost.sm', { href: topicHref(id, names) }, icon('outline'), 'Open the outline'))
      : null);
}

// ------------------------------------------------------------------- reader

async function readerView(id, query, index, names) {
  const lec = await lecture(id);
  if (!lec) return page('narrow', emptyState('That lecture isn’t in the index.', 'It may have been renamed. Rebuild the index or go back to the list.', h('a.btn', { href: '#/lectures' }, 'All lectures')));
  const meta = names.subject(lec.subject);
  const p = prefs();
  const chunks = lec.chunks;
  let activeTopic = query.tips ? '#tips' : query.topic || null;
  let current = -1;
  let follow = true;

  // ---- player
  const src = mediaUrl(lec, p.mediaBase);
  const video = src ? h('video.lec-video', { controls: true, preload: 'metadata', playsinline: true, src }) : null;
  const note = h('p.lec-player-note.muted');
  const baseInput = h('input.line-input.lec-base', { type: 'url', value: p.mediaBase, 'aria-label': 'Media server address', spellcheck: 'false' });
  const mediaHelp = h('details.lec-media-help',
    h('summary', 'Video not playing?'),
    h('p', 'Start the media server on the folder that holds the videos, then reload:'),
    h('pre.lec-cmd', `python3 tools/lectures.py serve-media --root "/path/to/videos"`),
    h('label.lec-base-row', h('span.smallcaps', 'Media server'), baseInput,
      h('button.btn.sm', { type: 'button', onclick: () => { setPref('mediaBase', baseInput.value.trim() || DEFAULT_MEDIA_BASE); location.reload(); } }, 'Save')));
  if (video) {
    video.playbackRate = p.rate;
    video.addEventListener('ratechange', () => setPref('rate', video.playbackRate));
    video.addEventListener('error', () => { note.textContent = 'The video couldn’t be loaded from the media server.'; mediaHelp.open = true; });
    video.addEventListener('timeupdate', () => {
      const i = passageAt(chunks, video.currentTime + 0.25);
      if (i !== current) mark(i, follow && !video.paused);
    });
    let lastSave = 0;
    video.addEventListener('timeupdate', () => {
      if (Date.now() - lastSave > 5000) { lastSave = Date.now(); savePosition(lec.id, video.currentTime); }
    });
  }

  // ---- passages
  const items = chunks.map(ch => {
    const stampBtn = h('button.lec-stamp.num', {
      type: 'button', 'aria-label': `Play from ${fmtClock(ch.start)}`, disabled: !video,
      onclick: () => seek(ch.start, true),
    }, fmtClock(ch.start));
    const tags = ch.tags.map((t, k) => h(k === 0 ? 'a.pill.lec-topic' : 'a.pill.lec-topic.minor', { href: topicHref(t.topic, names), title: `match ${t.score}` }, names.topic(t.topic).title));
    const rules = (ch.rules || []).map(r => h('a.lec-rule', { href: ruleHref(r) }, icon('link'), r.rule.split('.').pop().replace(/-/g, ' ')));
    return h('li.lec-passage', { class: ch.tips?.length ? 'has-tip' : null, dataset: { i: ch.i, topics: ch.tags.map(t => t.topic).join(' ') } },
      stampBtn,
      h('div.lec-passage-body',
        h('p.lec-text', withTips(ch.text, ch.tips)),
        tags.length || rules.length ? h('div.lec-tags', tags, rules) : null));
  });
  const list = h('ol.lec-passages', items);

  function mark(i, scroll) {
    if (current >= 0) items[current]?.classList.remove('is-current');
    current = i;
    if (i < 0) return;
    items[i].classList.add('is-current');
    if (scroll) {
      const r = items[i].getBoundingClientRect();
      if (r.top < 120 || r.bottom > innerHeight - 40) items[i].scrollIntoView({ block: 'center', behavior: 'smooth' });
    }
  }
  function seek(t, play) {
    const i = passageAt(chunks, t + 0.01);
    mark(i, false);
    if (!video) return;
    const go = () => { video.currentTime = t; if (play) video.play().catch(() => {}); };
    if (video.readyState >= 1) go(); else video.addEventListener('loadedmetadata', go, { once: true });
  }

  // ---- topic filter
  const topicChips = (lec.topTopics || []).map(t => h('button.chip', {
    type: 'button', 'aria-pressed': String(activeTopic === t.topic), dataset: { topic: t.topic },
    onclick: () => { activeTopic = activeTopic === t.topic ? null : t.topic; applyFilter(); },
  }, names.topic(t.topic).title, h('span.muted.num', ` ${Math.max(1, Math.round(t.seconds / 60))}m`)));
  const tipCount = chunks.filter(ch => ch.tips?.length).length;
  if (tipCount) {
    topicChips.unshift(h('button.chip.lec-tips-chip', {
      type: 'button', 'aria-pressed': String(activeTopic === '#tips'), dataset: { topic: '#tips' },
      onclick: () => { activeTopic = activeTopic === '#tips' ? null : '#tips'; applyFilter(); },
    }, icon('star'), 'Exam tips', h('span.muted.num', ` ${tipCount}`)));
  }
  function applyFilter() {
    for (const c of topicChips) c.setAttribute('aria-pressed', String(c.dataset.topic === activeTopic));
    for (const li of items) {
      li.hidden = activeTopic === '#tips' ? !li.classList.contains('has-tip')
        : !!activeTopic && !li.dataset.topics.split(' ').includes(activeTopic);
    }
  }

  // ---- neighbours in the same folder
  const sameFolder = index.lectures.filter(l => l.folder === lec.folder && l.subject === lec.subject);
  const pos = sameFolder.findIndex(l => l.id === lec.id);
  const prev = sameFolder[pos - 1];
  const next = sameFolder[pos + 1];

  const view = page('lectures-page lec-reader',
    h('div.crumbs', backLink('#/lectures', 'Lectures'), lec.folder ? h('span.smallcaps.muted', lec.folder) : null),
    h('header.head.lec-head', { style: meta.tab ? { '--tab': meta.tab } : null },
      h('div.kicker.smallcaps', subjectDot(meta), h('span', meta.name)),
      h('h1', lec.title),
      h('p.lec-meta.num.muted',
        `${fmtDuration(lec.duration)} · ${plural(chunks.length, 'passage')}`,
        lec.timing === 'estimated' ? ' · timestamps estimated (no timing in the transcript)' : '',
        src ? '' : ' · no video found next to the transcript'),
      topicChips.length ? h('div.chips.lec-topic-filter', { role: 'group', 'aria-label': 'Show only passages on a topic' }, topicChips) : null),
    video ? h('div.lec-player', video, note,
      h('label.toggle.lec-follow', h('input', { type: 'checkbox', checked: true, onchange: e => { follow = e.target.checked; } }), 'Follow along'),
      mediaHelp) : null,
    list,
    h('nav.pager',
      prev ? h('a.pager-link.prev', { href: `#/lectures/${encodeURIComponent(prev.id)}` }, h('span.smallcaps', '← Previous'), h('span', prev.title)) : h('span'),
      next ? h('a.pager-link.next', { href: `#/lectures/${encodeURIComponent(next.id)}` }, h('span.smallcaps', 'Next →'), h('span', next.title))
        : h('a.pager-link.next', { href: '#/lectures' }, h('span.smallcaps', 'Done'), h('span', 'All lectures'))));

  applyFilter();
  const startAt = query.t != null ? Number(query.t) : (p.positions[lec.id] || null);
  if (startAt != null && !Number.isNaN(startAt)) {
    requestAnimationFrame(() => {
      seek(startAt, false);
      if (query.t != null && current >= 0) items[current].scrollIntoView({ block: 'center' });
    });
  }

  return {
    el: view,
    destroy() {
      if (video) { savePosition(lec.id, video.currentTime); video.pause(); video.removeAttribute('src'); video.load(); }
    },
  };
}
