// Where Florida differs — every Florida rule whose outline notes how Florida departs from
// the MBE/UBE (majority) rule, gathered into one searchable, printable list.
//   #/florida/differences             all Florida subjects
//   #/florida/differences?subject=id  one subject

import { h, swap, debounce, plural } from '../lib/dom.js';
import { allSubjects } from '../lib/content.js';
import { page, header, emptyState } from '../ui/kit.js';
import { icon } from '../ui/icons.js';

export const title = 'Where Florida differs';

function norm(s) {
  return String(s || '').toLowerCase();
}

export async function render(_, query) {
  const subs = (await allSubjects()).filter(s => s.meta.group === 'florida' || String(s.id).startsWith('fl-'));
  const items = [];
  for (const s of subs) {
    for (const t of s.topics) {
      for (const r of t.rules) {
        if (r.split) items.push({ s, t, r, hay: norm([r.title, r.rule, r.split, r.authority, t.title, s.meta.name].join(' ')) });
      }
    }
  }
  if (!items.length) {
    return page('narrow', header({ sec: '02', kicker: 'Florida Part A', title: 'Where Florida differs' }),
      emptyState('No Florida subjects are installed.', 'Install the Florida pack, then set your jurisdiction to Florida in Settings.'));
  }

  let subject = query.subject || '';
  const input = h('input.fd-search', { type: 'search', placeholder: 'Filter: hearsay, homestead, alimony, 20 days…', 'aria-label': 'Filter differences', autocomplete: 'off' });
  const list = h('div.fd-list');
  const count = h('span.muted.num');
  const chips = h('div.chips.fd-chips', { role: 'group', 'aria-label': 'Subject' },
    [['', 'All']].concat(subs.filter(s => items.some(i => i.s === s)).map(s => [s.id, s.meta.short || s.meta.name])).map(([id, label]) =>
      h('button.chip', {
        type: 'button', 'aria-pressed': String(subject === id), dataset: { s: id },
        onclick: () => { subject = id; for (const c of chips.children) c.setAttribute('aria-pressed', String(c.dataset.s === subject)); paint(); },
      }, label)));

  function paint() {
    const q = norm(input.value).trim();
    const words = q.split(/\s+/).filter(Boolean);
    const shown = items.filter(i => (!subject || i.s.id === subject) && words.every(w => i.hay.includes(w)));
    count.textContent = plural(shown.length, 'difference');
    const groups = [];
    for (const i of shown) {
      let g = groups[groups.length - 1];
      if (!g || g.s !== i.s) { g = { s: i.s, rows: [] }; groups.push(g); }
      g.rows.push(i);
    }
    swap(list, groups.length ? groups.map(g => h('section.fd-subject', { style: { '--tab': g.s.meta.tab } },
      h('h2.fd-subject-head', h('span.tab-dot'), g.s.meta.name, h('span.muted.num', ` ${g.rows.length}`)),
      g.rows.map(({ s, t, r }) => h('article.fd-item',
        h('div.fd-item-head',
          h('a.fd-rule', { href: `#/outlines/${encodeURIComponent(s.id)}/${encodeURIComponent(t.id)}?rule=${encodeURIComponent(r.id)}` }, r.title),
          h('span.smallcaps.muted', t.title)),
        h('p.fd-split', h('span.fd-label.smallcaps', 'Florida'), r.split),
        h('details.fd-more', h('summary', 'Florida rule'), h('p', r.rule), r.authority ? h('p.muted.small', r.authority) : null)))))
      : emptyState('Nothing matches.', 'Try fewer words or another subject.'));
  }
  input.addEventListener('input', debounce(paint, 120));
  paint();

  return page('fd-page',
    header({
      sec: '02', kicker: 'Florida Part A', title: 'Where Florida differs',
      lede: 'Every rule where Florida departs from the MBE or majority rule, the points Part A likes to test. Each links to the full rule in the outline.',
      aside: h('div.fd-tools', count, h('button.btn.ghost.sm', { type: 'button', onclick: () => print() }, icon('print'), 'Print')),
    }),
    h('div.fd-bar', icon('search'), input),
    chips,
    list);
}
