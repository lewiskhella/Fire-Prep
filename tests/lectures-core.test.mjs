// node --test tests/lectures-core.test.mjs   (Node 18+). Pure-function tests for app/js/lib/lectures-core.js.
import test from 'node:test';
import assert from 'node:assert/strict';
import { stem, tokenize, fmtClock, fmtDuration, buildIndex, search, highlightRuns, snippet, passageAt, parseRoute, momentsFor } from '../app/js/lib/lectures-core.js';

test('stemming matches the Python side', () => {
  assert.equal(stem('parties'), 'party');
  assert.equal(stem('witnesses'), 'witness');
  assert.equal(stem('basis'), 'basis');
  assert.deepEqual(tokenize("The court's rulings"), ['court', 'rul']);
  assert.equal(stem('settled'), stem('settle'));
  assert.equal(stem('devises'), stem('devise'));
});

test('clock and duration formatting', () => {
  assert.equal(fmtClock(65), '1:05');
  assert.equal(fmtClock(3725), '1:02:05');
  assert.equal(fmtDuration(90 * 60), '1 h 30 min');
  assert.equal(fmtDuration(600), '10 min');
});

test('search ranks the passage with every term and the exact phrase first', () => {
  const idx = buildIndex([
    { lecture: 'a', chunk: 0, start: 0, text: 'Settlement talks and fees.' },
    { lecture: 'b', chunk: 0, start: 30, text: 'A proposal for settlement shifts fees when the judgment is 25 percent less.' },
    { lecture: 'c', chunk: 0, start: 60, text: 'Homestead cannot be devised freely.' },
  ]);
  const hits = search(idx, 'proposal for settlement');
  assert.equal(hits[0].lecture, 'b');
  assert.ok(!hits.some(h => h.lecture === 'c'));
  assert.deepEqual(search(idx, 'the of and'), []);
  assert.equal(search(idx, 'settlement', { filter: p => p.lecture === 'a' })[0].lecture, 'a');
});

test('highlight runs cover the whole text and mark stemmed matches', () => {
  const runs = highlightRuns('Parties may settle; the party settled.', 'party settle');
  assert.equal(runs.map(r => r.text).join(''), 'Parties may settle; the party settled.');
  assert.deepEqual(runs.filter(r => r.hit).map(r => r.text.trim()), ['Parties', 'settle', 'party', 'settled']);
});

test('snippet centres on the first hit', () => {
  const text = 'x '.repeat(300) + 'elective share of thirty percent ' + 'y '.repeat(300);
  const s = snippet(text, 'elective share', 120);
  assert.ok(s.includes('elective share'));
  assert.ok(s.startsWith('…') && s.endsWith('…'));
});

test('passageAt finds the passage playing at a time', () => {
  const chunks = [{ start: 0 }, { start: 75 }, { start: 150 }];
  assert.equal(passageAt(chunks, 0), 0);
  assert.equal(passageAt(chunks, 74.9), 0);
  assert.equal(passageAt(chunks, 151), 2);
  assert.equal(passageAt([], 5), -1);
});

test('routes and moments', () => {
  assert.deepEqual(parseRoute('#/lectures/abc?t=90'.replace('#/lectures/', '#/lecture/')), { kind: 'lecture', id: 'abc', t: 90 });
  assert.deepEqual(parseRoute('#/'), { kind: 'home' });
  const links = { topics: { 't': [['l1', 2, 30.5, 0.9]] }, rules: { 'r': [['l2', 0, 0, 0.5]] } };
  assert.deepEqual(momentsFor(links, 't'), [{ lecture: 'l1', chunk: 2, start: 30.5, score: 0.9 }]);
  assert.equal(momentsFor(links, 'r')[0].lecture, 'l2');
  assert.deepEqual(momentsFor(null, 't'), []);
});
