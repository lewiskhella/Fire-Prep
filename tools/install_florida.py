#!/usr/bin/env python3
"""Install the Florida Part A content pack into the Ruled app.

    python3 tools/install_florida.py "/Volumes/Extreme Pro/Bar Prep App"
    python3 tools/install_florida.py "/Volumes/Extreme Pro/Bar Prep App" --dry-run
    python3 tools/install_florida.py "/Volumes/Extreme Pro/Bar Prep App" --uninstall

What it does (every changed file is backed up to <app>/.florida-backup/<time>/):
  * copies florida/content/subjects/fl-*/ into content/subjects/
  * content/catalog.json        adds (or refreshes) the fl-* subjects, group "florida"
  * tools/validate_content.py   accepts "FL" as a topic exam
  * app/js/lib/content.js       jurisdiction track: Settings → jurisdiction "Florida"
                                shows MBE + Florida Part A (hides the MEE-only subjects);
                                any other jurisdiction hides Florida; blank shows all
  * app/js/views/outlines.js    a "Florida Part A" shelf in the binder
  * content/guide.json + catalog  Florida Bench Book sections (florida/guide-florida.json) and the
                                Florida exam profile; content.js shows them on the Florida track
  * app/js/ui/shell.js + views/essays.js  Florida track: "Part A Essays", no Performance Test
  * app/js/views/welcome.js     labels Florida subjects in onboarding
  * app/js/lib/planner.js       study-time weights for the Florida subjects, and (via the new
                                lib/florida-plan.js) a Florida calendar: Part A question sets and
                                three-essay Part A simulations instead of MPT/MEE work
  * app/js/views/fl-differences.js + css/florida.css (new): "Where Florida differs", every
                                rule whose outline notes a Florida departure (#/florida/differences),
                                linked from the Florida shelf; main.js route; index.html stylesheet
  * app/js/views/mbe.js         an "All Florida Part A" pool in MBE Drills
                                (#/mbe?subjects=fl&count=100&mode=exam = a timed Part A set)
Then it runs the validator on the Florida subjects.
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import installkit as kit  # noqa: E402
from installkit import REPO, InsertAfterLine, InsertBefore, JsonEdit, Replace  # noqa: E402

BACKUP = ".florida-backup"
PACK = REPO / "florida"
NEEDED = ["content/catalog.json", "app/js/lib/content.js", "tools/validate_content.py"]

WEIGHTS = ("  'fl-civil-procedure': 1, 'fl-constitutional-law': 0.9, 'fl-business-entities': 0.8, 'fl-wills': 0.9, 'fl-trusts': 0.7,\n"
           "  'fl-family-law': 0.9, 'fl-evidence': 0.9, 'fl-criminal': 0.9, 'fl-real-property': 0.9, 'fl-torts': 0.8, 'fl-ucc': 0.6,\n"
           "  'fl-professional-responsibility': 0.9,\n")

CATALOG_OLD = """export function catalog() {
  if (!catalogPromise) catalogPromise = getJSON('catalog.json', { subjects: [], exam: { components: [] } });
  return catalogPromise;
}"""
CATALOG_NEW = """export function catalog() {
  if (!catalogPromise) catalogPromise = getJSON('catalog.json', { subjects: [], exam: { components: [] } }).then(forTrack);
  return catalogPromise;
}

// Jurisdiction track (Settings -> jurisdiction): "Florida" studies the MBE subjects plus
// Florida Part A; any other jurisdiction studies the UBE (MBE + MEE); blank shows everything.
// Read straight from storage to avoid importing the store here. Takes effect on reload.
function trackOf() {
  let j = '';
  try { j = (JSON.parse(localStorage.getItem('ruled:v1') || '{}').profile || {}).jurisdiction || ''; } catch { /* storage unavailable */ }
  j = String(j).trim().toLowerCase();
  return !j ? '' : /florida|^fl\\.?$/.test(j) ? 'florida' : 'ube';
}

function forTrack(cat) {
  const t = trackOf();
  if (!t) return cat;
  const florida = t === 'florida';
  const keep = s => (florida ? s.group !== 'mee' : s.group !== 'florida');
  return { ...cat, exam: florida && cat.examFlorida ? cat.examFlorida : cat.exam, subjects: (cat.subjects || []).filter(keep) };
}

// Bench Book: Florida sections first for the Florida track (UBE-only sections hidden);
// hidden for other jurisdictions; everything when no jurisdiction is set.
async function forTrackGuide(g) {
  const t = trackOf();
  const secs = (g && g.sections) || [];
  const isFl = s => String(s.id).startsWith('florida-');
  if (t === 'florida') {
    const cat = await getJSON('catalog.json', {});
    const hide = new Set((cat.examFlorida && cat.examFlorida.hideGuide) || []);
    return { ...g, sections: [...secs.filter(isFl), ...secs.filter(s => !isFl(s) && !hide.has(s.id))] };
  }
  return t ? { ...g, sections: secs.filter(s => !isFl(s)) } : g;
}"""


def pack_subjects() -> list[str]:
    base = PACK / "content" / "subjects"
    return sorted(p.name for p in base.iterdir() if p.is_dir() and any(p.glob("*.json"))) if base.exists() else []


def merge_catalog(data: dict) -> dict:
    entries = json.loads((PACK / "catalog-florida.json").read_text(encoding="utf-8"))["subjects"]
    present = set(pack_subjects())
    by_id = {s["id"]: s for s in entries if s["id"] in present}
    subjects = []
    for s in data.get("subjects", []):
        subjects.append(by_id.pop(s.get("id"), s) if s.get("id") in by_id else s)
    subjects.extend(by_id.values())
    out = dict(data)
    out["subjects"] = subjects
    return out


def _guide_pack():
    p = PACK / "guide-florida.json"
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else None


def add_exam_profile(data: dict) -> dict:
    g = _guide_pack()
    if not g or "exam" not in g:
        return data
    exam = dict(g["exam"])
    exam["hideGuide"] = list(g.get("hide", []))
    out = dict(data)
    out["examFlorida"] = exam
    return out


def merge_guide(data: dict) -> dict:
    g = _guide_pack()
    if not g:
        return data
    out = dict(data)
    kept = [s for s in data.get("sections", []) if not str(s.get("id", "")).startswith("florida-")]
    out["sections"] = kept + list(g.get("sections", []))
    return out


class CatalogEdit(JsonEdit):
    def apply(self, text):
        try:
            data = json.loads(text)
        except json.JSONDecodeError:
            return None
        out = self.fn(data)
        return text if out == data else json.dumps(out, ensure_ascii=False, indent=2) + "\n"


PATCHES = [
    CatalogEdit("content/catalog.json", "Florida subjects in the catalog", merge_catalog),
    Replace("tools/validate_content.py", '"FL"', "FL exam tag in the validator",
            [('EXAMS = {"MBE", "MEE"}', 'EXAMS = {"MBE", "MEE", "FL"}')]),
    Replace("app/js/lib/content.js", "forTrack", "jurisdiction track filter", [(CATALOG_OLD, CATALOG_NEW)]),
    Replace("app/js/lib/content.js", "forTrackGuide)", "Florida Bench Book sections", [
        ("export const guide = () => getJSON('guide.json', { sections: [] });",
         "export const guide = () => getJSON('guide.json', { sections: [] }).then(forTrackGuide);"),
    ]),
    CatalogEdit("content/catalog.json", "Florida exam profile in the catalog", lambda d: add_exam_profile(d)),
    CatalogEdit("content/guide.json", "Florida Bench Book sections", lambda d: merge_guide(d)),
    Replace("app/js/views/outlines.js", "group === 'florida'", "Florida Part A shelf", [
        ("const mee = subs.filter(s => s.meta.group !== 'mbe');",
         "const mee = subs.filter(s => s.meta.group !== 'mbe' && s.meta.group !== 'florida');\n"
         "  const fla = subs.filter(s => s.meta.group === 'florida');"),
        ("    h('div.grid.three', mee.map(card)));",
         "    mee.length ? h('h2.section', 'Tested on the MEE only', h('span.count', mee.length)) : null,\n"
         "    mee.length ? h('div.grid.three', mee.map(card)) : null,\n"
         "    fla.length ? h('h2.section', 'Florida Part A', h('span.count', fla.length), h('a.fl-shelf-link', { href: '#/florida/differences' }, 'Where Florida differs →')) : null,\n"
         "    fla.length ? h('div.grid.three', fla.map(card)) : null);"),
        ("    h('h2.section', 'Tested on the MEE only', h('span.count', mee.length)),\n", ""),
    ]),
    Replace("app/js/views/welcome.js", "includes('FL')", "Florida label in onboarding",
            [("s.exams.includes('MBE') ? ' MBE + MEE' : ' MEE'",
              "s.exams.includes('FL') ? ' Florida Part A' : s.exams.includes('MBE') ? ' MBE + MEE' : ' MEE'")]),
    Replace("app/js/views/mbe.js", "flIds", "'All Florida Part A' drill pool", [
        ("const mbeIds = subs.filter(s => s.meta.exams.includes('MBE')).map(s => s.id);",
         "const mbeIds = subs.filter(s => s.meta.exams.includes('MBE')).map(s => s.id);\n"
         "  const flIds = subs.filter(s => s.meta.exams.includes('FL')).map(s => s.id);"),
        ("const chosen = new Set(pre.includes('mbe') ? mbeIds : pre.length ? pre : mbeIds);",
         "const chosen = new Set(pre.includes('mbe') ? mbeIds : pre.includes('fl') ? flIds : pre.length ? pre : mbeIds);"),
        ("}, 'All MBE subjects'),",
         "}, 'All MBE subjects'),\n"
         "      ...(flIds.length ? [h('button.chip', { type: 'button', 'aria-pressed': flIds.every(id => chosen.has(id)) && chosen.size === flIds.length ? 'true' : 'false', "
         "onclick: () => { chosen.clear(); flIds.forEach(id => chosen.add(id)); paint(); } }, 'All Florida Part A')] : []),"),
    ]),
    InsertBefore("app/js/main.js", "'/florida/differences'", "route #/florida/differences", "route('*'",
                 "route('/florida/differences', () => import('./views/fl-differences.js'));\n"),
    InsertAfterLine("app/index.html", "css/florida.css", "Florida stylesheet link", 'href="css/views.css"',
                    '  <link rel="stylesheet" href="css/florida.css">\n'),
    Replace("app/js/lib/planner.js", "floridaize", "Florida calendar (Part A sets/essays instead of MPT/MEE)", [
        ("export function buildPlan(profile, subjects, today = new Date()) {",
         "import { floridaize } from './florida-plan.js';\n\n"
         "export function buildPlan(profile, subjects, today = new Date()) {\n"
         "  return floridaize(buildPlanBase(profile, subjects, today), profile, subjects);\n"
         "}\n\n"
         "function buildPlanBase(profile, subjects, today = new Date()) {"),
    ]),
    Replace("app/js/ui/shell.js", "trackNav", "Florida navigation (Part A Essays; no Performance Test)", [
        ("function navList(path, onPick) {",
         "// Florida track: essays are Part A essays and there is no MPT.\n"
         "function trackNav() {\n"
         "  const fl = /florida|^fl\\.?$/.test(String(store.state.profile.jurisdiction || '').trim().toLowerCase());\n"
         "  if (!fl) return NAV;\n"
         "  return NAV.filter(i => i.path !== '/mpt').map(i => (i.path === '/essays' ? { ...i, label: 'Part A Essays' } : i));\n"
         "}\n\n"
         "function navList(path, onPick) {"),
        ("return h('ul.nav', NAV.map(item => item.group", "return h('ul.nav', trackNav().map(item => item.group"),
    ]),
    Replace("app/js/views/essays.js", "floridaTrack", "Part A essays heading on the Florida track", [
        ("export const title = 'MEE Essays';",
         "export const title = 'MEE Essays';\n"
         "const floridaTrack = () => { try { return /florida|^fl\\.?$/.test(String((JSON.parse(localStorage.getItem('ruled:v1') || '{}').profile || {}).jurisdiction || '').trim().toLowerCase()); } catch { return false; } };"),
        ("      title: 'MEE Essays',", "      title: floridaTrack() ? 'Part A Essays' : 'MEE Essays',"),
        ("lede: 'Thirty minutes each, written on pleading paper against a running clock.",
         "lede: floridaTrack() ? 'An hour each for Florida Part A, written on pleading paper against a running clock. Then grade yourself issue by issue against what a grader looks for, and read the model answer beside your own.' : 'Thirty minutes each, written on pleading paper against a running clock."),
    ]),
    InsertAfterLine("app/js/lib/planner.js", "'fl-wills'", "Florida study-time weights",
                    "'conflict-of-laws': 0.45,", WEIGHTS),
]


def validate(app: Path, subjects: list[str]) -> bool:
    ok = True
    for sid in subjects:
        r = subprocess.run([sys.executable, "tools/validate_content.py", sid], cwd=app, capture_output=True, text=True)
        lines = [l for l in r.stdout.splitlines() if l.strip()]
        summary = next((l for l in lines if l.strip().startswith(sid)), sid)
        print(f"  {summary.strip()}  ->  {lines[-1] if lines else ''}")
        if r.returncode != 0:
            ok = False
            for l in lines:
                if l.startswith(("error", "ERR")) or ": " in l and "error" in l.lower():
                    print("     " + l)
    return ok


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("app", help="the Ruled app folder, e.g. '/Volumes/Extreme Pro/Bar Prep App'")
    ap.add_argument("--dry-run", action="store_true", help="show what would change")
    ap.add_argument("--uninstall", action="store_true", help="restore the files backed up by the first install")
    args = ap.parse_args(argv)
    app = Path(args.app).expanduser().resolve()
    if not app.is_dir():
        sys.exit(f"not a folder: {app}")
    if args.uninstall:
        return kit.uninstall(app, args.dry_run, BACKUP)
    kit.check_target(app, NEEDED)
    subjects = pack_subjects()
    if not subjects:
        sys.exit("the Florida pack has no subjects yet (florida/content/subjects/ is empty)")
    copies = [(f"florida/content/subjects/{sid}", f"content/subjects/{sid}") for sid in subjects]
    copies += [("app/js/views/fl-differences.js", "app/js/views/fl-differences.js"), ("app/css/florida.css", "app/css/florida.css"),
               ("app/js/lib/florida-plan.js", "app/js/lib/florida-plan.js")]
    code = kit.install(app, args.dry_run, copies, PATCHES, BACKUP)
    if not args.dry_run:
        print("\nValidating the Florida subjects:")
        if not validate(app, subjects):
            code = 1
    print("\nTo study the Florida track: Settings -> jurisdiction 'Florida', then reload the app.")
    return code


if __name__ == "__main__":
    sys.exit(main())
