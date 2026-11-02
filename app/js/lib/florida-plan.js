// Adapts the study calendar for the Florida track (Settings → jurisdiction "Florida").
// Florida's exam is Part A (Florida essays + Florida multiple choice) and Part B (the MBE);
// there is no MPT or MEE. buildPlan() output is post-processed so task ids, and therefore
// completion marks, stay stable: only kind, title, detail, minutes and href change.

export function isFloridaTrack(profile) {
  const j = String((profile && profile.jurisdiction) || '').trim().toLowerCase();
  return /florida|^fl\.?$/.test(j);
}

export function floridaize(plan, profile, subjects) {
  if (!plan || !plan.days || !isFloridaTrack(profile)) return plan;
  const fl = (subjects || []).filter(s => s.meta && (s.meta.group === 'florida' || String(s.id).startsWith('fl-')));
  if (!fl.length) return plan;
  const withEssays = fl.filter(s => s.essays && s.essays.length);
  let rot = 0;
  const nextEssaySubject = () => (withEssays.length ? withEssays[rot++ % withEssays.length].id : null);

  for (const tasks of plan.days.values()) {
    for (const t of tasks) {
      if (t.kind === 'mpt' && /^Simulated/i.test(t.title)) {
        Object.assign(t, {
          kind: 'mbe', title: 'Simulated Part A multiple choice: 100 questions',
          detail: 'Three hours of Florida-law questions in exam mode, like the Part A afternoon. Review every miss.',
          minutes: 180, href: '#/mbe?subjects=fl&count=100&mode=exam',
        });
      } else if (t.kind === 'mpt') {
        const n = t.minutes >= 90 ? 50 : 25;
        Object.assign(t, {
          kind: 'mbe', title: `Florida Part A set: ${n} questions`,
          detail: 'Mixed Florida subjects, timed at 1.8 minutes a question.',
          minutes: Math.round(n * 1.8 + 15), href: `#/mbe?subjects=fl&count=${n}&mode=exam`,
        });
      } else if (t.kind === 'essay' && /^Simulated/i.test(t.title)) {
        const sid = nextEssaySubject();
        Object.assign(t, {
          title: 'Simulated Part A essays: three Florida essays back to back',
          detail: 'One hour per essay, three hours in all, then grade each against its model answer.',
          minutes: 200, href: sid ? `#/essays?subject=${sid}&next=1` : '#/essays',
        });
      } else if (t.kind === 'essay' && String(t.subject || '').startsWith('fl-')) {
        t.detail = String(t.detail || '').replace(/30 minutes/g, '60 minutes');
        t.minutes = Math.max(t.minutes || 0, 75);
      } else if (t.kind === 'essay' && t.subject && !String(t.subject).startsWith('fl-')) {
        // A UBE essay subject slipped into a Florida plan: point it at a Florida essay instead.
        const sid = nextEssaySubject();
        if (sid) Object.assign(t, { title: `Essay: ${fl.find(s => s.id === sid).meta.short}`, detail: 'Timed at 60 minutes. Grade it the same day.', minutes: 75, href: `#/essays?subject=${sid}` });
      }
    }
  }
  return plan;
}
