// "On tape" box for an outline topic: the best lecture moments for the topic
// and its rules, from the lecture index. Renders nothing (and costs
// one failed fetch) when no index has been built.

import { h, plural } from '../lib/dom.js';
import { lectureIndex, lectureLinks } from '../lib/lectures.js';
import { fmtClock, momentsFor } from '../lib/lectures-core.js';
import { icon } from './icons.js';

export function lectureAside(topic, { max = 4 } = {}) {
  const box = h('aside.lec-aside', { hidden: true, 'aria-label': 'Lectures on this topic' });
  (async () => {
    const [index, links] = await Promise.all([lectureIndex(), lectureLinks()]);
    if (!index || !links) return;
    const byId = new Map(index.lectures.map(l => [l.id, l]));
    const seen = new Set();
    const rows = [];
    const add = (m, why) => {
      if (seen.has(m.lecture) || !byId.has(m.lecture)) return;
      seen.add(m.lecture);
      rows.push({ ...m, why });
    };
    momentsFor(links, topic.id).forEach(m => add(m, null));
    for (const r of topic.rules || []) momentsFor(links, r.id).forEach(m => add(m, r.title));
    if (!rows.length) return;
    rows.sort((a, b) => b.score - a.score);
    box.append(...[
      h('h2.smallcaps', icon('play'), 'On tape'),
      h('ol', rows.slice(0, max).map(m => h('li',
        h('a', { href: `#/lectures/${encodeURIComponent(m.lecture)}?t=${Math.floor(m.start)}` },
          h('span', byId.get(m.lecture).title), h('time.num', fmtClock(m.start))),
        m.why ? h('span.muted', m.why) : null))),
      (links.tips?.[topic.id] || []).filter(([lid]) => byId.has(lid)).slice(0, 2).map(([lid, , start, text]) =>
        h('a.lec-aside-tip', { href: `#/lectures/${encodeURIComponent(lid)}?t=${Math.floor(start)}` }, h('q', text))),
      rows.length > max ? h('a.linkish', { href: `#/lectures?topic=${encodeURIComponent(topic.id)}` }, `All ${plural(rows.length, 'lecture')} →`) : null,
    ].flat().filter(Boolean));
    box.hidden = false;
  })();
  return box;
}
