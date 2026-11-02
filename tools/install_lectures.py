#!/usr/bin/env python3
"""Install the Lectures section (§ 11) and transcript tools into the Ruled app.

    python3 tools/install_lectures.py "/Volumes/Extreme Pro/Bar Prep App"
    python3 tools/install_lectures.py "/Volumes/Extreme Pro/Bar Prep App" --dry-run
    python3 tools/install_lectures.py "/Volumes/Extreme Pro/Bar Prep App" --uninstall

What it does (every changed file is backed up to <app>/.lectures-backup/<time>/):
  * copies the new files (views/lectures.js, lib/lectures*.js, ui/lecture-links.js,
    css/lectures.css, tools/lectures.py, tools/lecturelib/)
  * main.js      adds the #/lectures and #/lectures/:id routes
  * shell.js     adds "§11 Lectures" to the navigation
  * index.html   links css/lectures.css
  * topic.js     shows an "On tape" box (best lecture moments) on each outline topic

Each edit is anchored on a line of the existing code and is skipped, with a
warning, if that line has changed, so it is safe to run while the app is
evolving and safe to run twice.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import installkit as kit  # noqa: E402
from installkit import InsertAfterLine, InsertBefore, Patch  # noqa: E402

BACKUP = ".lectures-backup"
FILES = [
    "app/js/lib/lectures.js",
    "app/js/lib/lectures-core.js",
    "app/js/views/lectures.js",
    "app/js/ui/lecture-links.js",
    "app/css/lectures.css",
    "tools/lectures.py",
    "tools/lecturelib",
]

ROUTES = "route('/lectures', () => import('./views/lectures.js'));\nroute('/lectures/:id', () => import('./views/lectures.js'));\n"
NAV_ITEM = "  { sec: '11', path: '/lectures', label: 'Lectures', icon: 'play' },\n"
CSS_LINK = '  <link rel="stylesheet" href="css/lectures.css">\n'
TOPIC_IMPORT = "import { lectureAside } from '../ui/lecture-links.js';\n"


class TopicAside(Patch):
    """Import lectureAside and place it just before the topic's rule list."""

    def apply(self, text):
        anchor_import = "from '../ui/rule.js';"
        anchor_list = "rules.length ? list : emptyState("
        if anchor_import not in text or anchor_list not in text:
            return None
        text = InsertAfterLine(self.path, "", "", anchor_import, TOPIC_IMPORT).apply(text)
        i = text.find(anchor_list)
        line_start = text.rfind("\n", 0, i) + 1
        indent = text[line_start:i]
        if indent.strip():
            indent = " " * (len(indent) - len(indent.lstrip()))
            return text[:i] + "lectureAside(t),\n" + indent + text[i:]
        return text[:line_start] + indent + "lectureAside(t),\n" + text[line_start:]


PATCHES = [
    InsertBefore("app/js/main.js", "'/lectures'", "routes #/lectures and #/lectures/:id", "route('*'", ROUTES),
    InsertAfterLine("app/js/ui/shell.js", "path: '/lectures'", "navigation entry §11 Lectures", "path: '/guide'", NAV_ITEM),
    InsertAfterLine("app/index.html", "css/lectures.css", "stylesheet link", 'href="css/views.css"', CSS_LINK),
    TopicAside("app/js/views/topic.js", "lectureAside", "\"On tape\" box on outline topics"),
]

NEEDED = ["app/js/main.js", "app/index.html", "app/js/ui/shell.js", "app/js/lib/dom.js", "app/js/ui/kit.js", "app/js/lib/content.js"]


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
    code = kit.install(app, args.dry_run, [(f, f) for f in FILES], PATCHES, BACKUP)
    print("\nNext: build the index, then open http://localhost:4321/app/#/lectures")
    print('  python3 tools/lectures.py build --transcripts "/path/to/Florida Bar videos" --library .')
    return code


if __name__ == "__main__":
    sys.exit(main())
