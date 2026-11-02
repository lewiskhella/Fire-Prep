"""Tests for tools/install_lectures.py against a minimal stand-in for the Ruled app."""
from __future__ import annotations

import io
import shutil
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))

import install_lectures as inst  # noqa: E402

MAIN = """import { route } from './lib/router.js';
route('/', () => import('./views/docket.js'));
route('/guide', () => import('./views/guide.js'));
route('*', () => import('./views/notfound.js'));
"""
SHELL = """export const NAV = [
  { sec: '10', path: '/guide', label: 'Bench Book', icon: 'guide' },
];
"""
HTML = """<head>
  <link rel="stylesheet" href="css/views.css">
  <link rel="stylesheet" href="css/print.css" media="print">
</head>
"""
TOPIC = """import { ruleArticle } from '../ui/rule.js';

export async function render() {
  const view = page('outline-page',
    header,
    rules.length ? list : emptyState('No starred rules in this topic yet.', 'Star a rule.'),
    pager);
  return view;
}
"""


class InstallerTests(unittest.TestCase):
    def setUp(self):
        self.app = Path(tempfile.mkdtemp()) / "Bar Prep App"
        for rel, text in {
            "app/js/main.js": MAIN, "app/js/ui/shell.js": SHELL, "app/index.html": HTML, "app/js/views/topic.js": TOPIC,
            "app/js/lib/dom.js": "", "app/js/ui/kit.js": "", "app/js/lib/content.js": "",
        }.items():
            p = self.app / rel
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(text)

    def tearDown(self):
        shutil.rmtree(self.app.parent, ignore_errors=True)

    def run_inst(self, *args):
        buf = io.StringIO()
        with redirect_stdout(buf):
            code = inst.main([str(self.app), *args])
        return code, buf.getvalue()

    def test_install_is_idempotent_and_reversible(self):
        code, out = self.run_inst()
        self.assertEqual(code, 0, out)
        main = (self.app / "app/js/main.js").read_text()
        self.assertLess(main.index("route('/lectures/:id'"), main.index("route('*'"))
        self.assertIn("path: '/lectures'", (self.app / "app/js/ui/shell.js").read_text())
        html = (self.app / "app/index.html").read_text()
        self.assertLess(html.index("css/views.css"), html.index("css/lectures.css"))
        topic = (self.app / "app/js/views/topic.js").read_text()
        self.assertIn("import { lectureAside } from '../ui/lecture-links.js';", topic)
        self.assertIn("    lectureAside(t),\n    rules.length ? list", topic)
        self.assertTrue((self.app / "tools/lecturelib/pipeline.py").exists())
        self.assertIn("private/", (self.app / ".gitignore").read_text())

        code, out = self.run_inst()
        self.assertEqual(code, 0)
        self.assertEqual((self.app / "app/js/main.js").read_text().count("/lectures'"), 1)
        self.assertEqual(out.count("unchanged"), 4)

        code, _ = self.run_inst("--uninstall")
        self.assertEqual((self.app / "app/js/main.js").read_text(), MAIN)
        self.assertEqual((self.app / "app/js/views/topic.js").read_text(), TOPIC)
        self.assertFalse((self.app / "app/js/views/lectures.js").exists())
        self.assertFalse((self.app / "tools/lecturelib").exists())

    def test_missing_anchor_is_skipped_not_mangled(self):
        (self.app / "app/js/views/topic.js").write_text("// rewritten topic view\n")
        code, out = self.run_inst()
        self.assertEqual(code, 1)
        self.assertIn("SKIPPED     app/js/views/topic.js", out)
        self.assertEqual((self.app / "app/js/views/topic.js").read_text(), "// rewritten topic view\n")

    def test_dry_run_changes_nothing(self):
        self.run_inst("--dry-run")
        self.assertEqual((self.app / "app/js/main.js").read_text(), MAIN)
        self.assertFalse((self.app / "app/js/views/lectures.js").exists())

    def test_rejects_wrong_folder(self):
        with self.assertRaises(SystemExit):
            inst.main([str(self.app / "app")])


if __name__ == "__main__":
    unittest.main()
