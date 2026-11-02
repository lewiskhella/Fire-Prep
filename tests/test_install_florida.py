"""Tests for tools/install_florida.py against a minimal stand-in for the Ruled app."""
from __future__ import annotations

import io
import json
import shutil
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))

import install_florida as fl  # noqa: E402

CONTENT_JS = """let catalogPromise;
export function catalog() {
  if (!catalogPromise) catalogPromise = getJSON('catalog.json', { subjects: [], exam: { components: [] } });
  return catalogPromise;
}
export const guide = () => getJSON('guide.json', { sections: [] });
"""
OUTLINES_JS = """  const mbe = subs.filter(s => s.meta.group === 'mbe');
  const mee = subs.filter(s => s.meta.group !== 'mbe');

  return page('',
    h('h2.section', 'Tested on the MBE and the MEE', h('span.count', mbe.length)),
    h('div.grid.three', mbe.map(card)),
    h('h2.section', 'Tested on the MEE only', h('span.count', mee.length)),
    h('div.grid.three', mee.map(card)));
}
"""
VALIDATOR = 'EXAMS = {"MBE", "MEE"}\nprint("  TOTAL")\n'
PLANNER = "const BASE_WEIGHT = {\n  'family-law': 0.65, 'secured-transactions': 0.7, 'conflict-of-laws': 0.45,\n};\nexport function buildPlan(profile, subjects, today = new Date()) {\n  return 1;\n}\n"
WELCOME = "h('span.muted.smallcaps', s.exams.includes('MBE') ? ' MBE + MEE' : ' MEE')"
MBE_JS = """  const mbeIds = subs.filter(s => s.meta.exams.includes('MBE')).map(s => s.id);
  const chosen = new Set(pre.includes('mbe') ? mbeIds : pre.length ? pre : mbeIds);
    chips.replaceChildren(
      h('button.chip', { type: 'button', onclick: () => { paint(); } }, 'All MBE subjects'),
      ...subs.map(s => s));
"""
CATALOG = {"version": 1, "subjects": [{"id": "torts", "group": "mbe", "exams": ["MBE", "MEE"]}]}


class FloridaInstallerTests(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.app = self.tmp / "app-root"
        files = {"app/js/lib/content.js": CONTENT_JS, "app/js/views/outlines.js": OUTLINES_JS, "tools/validate_content.py": VALIDATOR,
                 "app/js/lib/planner.js": PLANNER, "app/js/views/welcome.js": WELCOME, "app/js/views/mbe.js": MBE_JS,
                 "app/js/ui/shell.js": "function navList(path, onPick) {\n  return h('ul.nav', NAV.map(item => item.group ? 1 : 2));\n}\n",
                 "app/js/views/essays.js": "export const title = 'MEE Essays';\nheader({\n      title: 'MEE Essays',\n      lede: 'Thirty minutes each, written on pleading paper against a running clock. Then grade.',\n});\n",
                 "content/guide.json": json.dumps({"sections": [{"id": "mee-method"}, {"id": "florida-old"}]}),
                 "app/js/main.js": "route('/', x);\nroute('*', y);\n", "app/index.html": '<link rel="stylesheet" href="css/views.css">\n', "content/catalog.json": json.dumps(CATALOG)}
        for rel, text in files.items():
            p = self.app / rel
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(text)
        # A one-subject pack so the test doesn't depend on the real content.
        self.pack = self.tmp / "pack"
        (self.pack / "content/subjects/fl-wills").mkdir(parents=True)
        (self.pack / "content/subjects/fl-wills/outline.json").write_text('{"subject": "fl-wills", "topics": []}')
        shutil.copy(ROOT / "florida/catalog-florida.json", self.pack / "catalog-florida.json")
        (self.pack / "guide-florida.json").write_text(json.dumps({"exam": {"name": "Florida", "short": "FL", "components": []}, "hide": ["mee-method"], "sections": [{"id": "florida-how", "title": "T", "kicker": "k", "body": ["b"]}]}))
        self._pack, fl.PACK = fl.PACK, self.pack
        self._validate, fl.validate = fl.validate, lambda app, subjects: True
        self._repo = fl.kit.REPO
        fl.kit.REPO = self.tmp  # copies resolve against the temp tree
        (self.tmp / "florida").symlink_to(self.pack)
        (self.tmp / "app").symlink_to(ROOT / "app")

    def tearDown(self):
        fl.PACK, fl.validate, fl.kit.REPO = self._pack, self._validate, self._repo
        shutil.rmtree(self.tmp, ignore_errors=True)

    def run_inst(self, *args):
        buf = io.StringIO()
        with redirect_stdout(buf):
            code = fl.main([str(self.app), *args])
        return code, buf.getvalue()

    def test_install_idempotent_and_reversible(self):
        code, out = self.run_inst()
        self.assertEqual(code, 0, out)
        cat = json.loads((self.app / "content/catalog.json").read_text())
        self.assertEqual([s["id"] for s in cat["subjects"]], ["torts", "fl-wills"])
        self.assertEqual(cat["examFlorida"]["hideGuide"], ["mee-method"])
        guide = json.loads((self.app / "content/guide.json").read_text())
        self.assertEqual([x["id"] for x in guide["sections"]], ["mee-method", "florida-how"])
        self.assertIn(".then(forTrackGuide)", (self.app / "app/js/lib/content.js").read_text())
        self.assertIn("trackNav().map(item => item.group", (self.app / "app/js/ui/shell.js").read_text())
        self.assertIn("floridaTrack() ? 'Part A Essays' : 'MEE Essays'", (self.app / "app/js/views/essays.js").read_text())
        self.assertEqual(cat["subjects"][1]["group"], "florida")
        self.assertTrue((self.app / "content/subjects/fl-wills/outline.json").exists())
        self.assertIn('"FL"', (self.app / "tools/validate_content.py").read_text())
        content = (self.app / "app/js/lib/content.js").read_text()
        self.assertIn(".then(forTrack)", content)
        outlines = (self.app / "app/js/views/outlines.js").read_text()
        self.assertIn("'Florida Part A'", outlines)
        self.assertEqual(outlines.count("'Tested on the MEE only'"), 1)
        planner = (self.app / "app/js/lib/planner.js").read_text()
        self.assertIn("'fl-wills': 0.9", planner)
        self.assertIn("return floridaize(buildPlanBase(profile, subjects, today), profile, subjects);", planner)
        self.assertTrue((self.app / "app/js/lib/florida-plan.js").exists())
        self.assertIn("includes('FL')", (self.app / "app/js/views/welcome.js").read_text())
        self.assertIn("'/florida/differences'", (self.app / "app/js/main.js").read_text())
        self.assertIn("css/florida.css", (self.app / "app/index.html").read_text())
        self.assertTrue((self.app / "app/js/views/fl-differences.js").exists())
        mbe = (self.app / "app/js/views/mbe.js").read_text()
        self.assertIn("pre.includes('fl') ? flIds", mbe)
        self.assertIn("'All Florida Part A'", mbe)

        code, out = self.run_inst()
        self.assertEqual(code, 0, out)
        self.assertEqual(out.count("unchanged"), 15, out)

        self.run_inst("--uninstall")
        self.assertEqual((self.app / "app/js/lib/content.js").read_text(), CONTENT_JS)
        self.assertEqual(json.loads((self.app / "content/catalog.json").read_text()), CATALOG)
        self.assertFalse((self.app / "content/subjects/fl-wills").exists())
        self.assertFalse((self.app / "app/js/views/fl-differences.js").exists())
        # Install again after an uninstall: a fresh backup set, and a second uninstall still restores.
        self.run_inst()
        self.run_inst("--uninstall")
        self.assertEqual((self.app / "app/js/lib/content.js").read_text(), CONTENT_JS)
        self.assertFalse((self.app / "content/subjects/fl-wills").exists())


if __name__ == "__main__":
    unittest.main()
