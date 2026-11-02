// node --test tests/florida-plan.test.mjs
import test from 'node:test';
import assert from 'node:assert/strict';
import { floridaize, isFloridaTrack } from '../app/js/lib/florida-plan.js';

const subjects = [
  { id: 'torts', meta: { group: 'mbe', short: 'Torts' }, essays: [{}] },
  { id: 'fl-wills', meta: { group: 'florida', short: 'FL Wills' }, essays: [{}] },
  { id: 'fl-torts', meta: { group: 'florida', short: 'FL Torts' }, essays: [{}] },
];
function plan() {
  return { days: new Map([
    ['2027-01-01', [
      { id: 'a', kind: 'mpt', title: 'Performance test', detail: 'Full 90-minute packet.', minutes: 90, href: '#/mpt' },
      { id: 'b', kind: 'essay', subject: 'fl-wills', title: 'FL Wills essay, timed', detail: '30 minutes on the clock, then grade.', minutes: 45, href: '#/essays?subject=fl-wills' },
      { id: 'c', kind: 'mbe', title: 'Mixed MBE set', minutes: 50, href: '#/mbe?subjects=mbe' },
    ]],
    ['2027-02-01', [
      { id: 'd', kind: 'mpt', title: 'Simulated MPT: one full packet', minutes: 110, href: '#/mpt' },
      { id: 'e', kind: 'essay', title: 'Simulated MEE: three essays back to back', minutes: 120, href: '#/essays' },
    ]],
  ]) };
}

test('track detection', () => {
  assert.ok(isFloridaTrack({ jurisdiction: 'Florida' }));
  assert.ok(isFloridaTrack({ jurisdiction: ' fl ' }));
  assert.ok(!isFloridaTrack({ jurisdiction: 'New York' }));
  assert.ok(!isFloridaTrack({ jurisdiction: '' }));
});

test('non-Florida plans are untouched', () => {
  const p = plan();
  const before = JSON.stringify([...p.days]);
  floridaize(p, { jurisdiction: 'New York' }, subjects);
  assert.equal(JSON.stringify([...p.days]), before);
});

test('Florida plan swaps MPT/MEE for Part A work and keeps ids', () => {
  const p = floridaize(plan(), { jurisdiction: 'Florida' }, subjects);
  const [a, b, c] = p.days.get('2027-01-01');
  assert.equal(a.id, 'a');
  assert.equal(a.kind, 'mbe');
  assert.match(a.href, /subjects=fl&count=50/);
  assert.match(b.detail, /60 minutes/);
  assert.equal(c.href, '#/mbe?subjects=mbe');
  const [d, e] = p.days.get('2027-02-01');
  assert.match(d.title, /Simulated Part A multiple choice/);
  assert.equal(d.href, '#/mbe?subjects=fl&count=100&mode=exam');
  assert.match(e.title, /Simulated Part A essays/);
  assert.match(e.href, /subject=fl-/);
  assert.equal(e.id, 'e');
});
