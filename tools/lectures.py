#!/usr/bin/env python3
"""Florida Bar lecture transcripts -> a private, searchable, topic-tagged index.

Commands (run from the app folder; only the Python standard library is needed):

  build        Parse every transcript under --transcripts, tag each ~75 s passage
               with subject/topic (and Ruled rule ids when --library is given),
               and write the index the app's Lectures section reads.
               Incremental: unchanged transcripts are skipped, so re-run it as
               more lectures finish transcribing (or use --watch).
  search       Full-text search across the lectures, with timestamps.
  coverage     Markdown report: lecture minutes per topic vs. what the library holds.
  brief        Authoring brief for one subject: what to cover and where to re-listen.
  corpus       Export plain text for the originality checker's reference corpus.
  serve-media  Serve the video folder with seeking support (for "play from here").

Typical use on the Mac:

  python3 tools/lectures.py build \\
      --transcripts "/Volumes/Extreme Pro/<Florida Bar videos folder>" \\
      --library . --out private/lectures
  python3 tools/lectures.py search "proposal for settlement" --out private/lectures
  python3 tools/lectures.py coverage --library . --out private/lectures > docs/LECTURE-COVERAGE.md
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from lecturelib import pipeline, taxonomy, textutil  # noqa: E402


def _subjects(args) -> list[taxonomy.Subject]:
    builtin = None if getattr(args, "no_florida", False) else "florida"
    library = Path(args.library) if getattr(args, "library", None) else None
    subjects = taxonomy.merged(library=library, builtin=builtin)
    if library and not any(s.source == "library" for s in subjects):
        print(f"warning: no content/subjects/*/outline.json found under {library}; using the built-in Florida taxonomy only", file=sys.stderr)
    return subjects


def cmd_build(args):
    subjects = _subjects(args)
    media_root = Path(args.media_root) if args.media_root else None
    transcripts = Path(args.transcripts)
    if not transcripts.is_dir():
        sys.exit(f"transcripts folder not found: {transcripts}")
    while True:
        manifest = pipeline.build(transcripts, Path(args.out), subjects, media_root=media_root)
        t = manifest["totals"]
        print(f"  {t['lectures']} lectures, {t['seconds'] / 3600:.1f} h, {t['words']:,} words -> {args.out}")
        for e in manifest["errors"][:10]:
            print(f"  skipped {e['path']}: {e['error']}")
        if not args.watch:
            break
        time.sleep(args.watch)


def cmd_search(args):
    results = pipeline.search(Path(args.out), args.query, limit=args.limit, subject=args.subject)
    if args.json:
        print(json.dumps(results, ensure_ascii=False, indent=1))
        return
    if not results:
        print("no matches")
    for r in results:
        print(f"[{r['score']:.2f}] {r['title']} @ {textutil.fmt_clock(r['start'])}")
        print("    " + pipeline.snippet(r["text"], args.query))


def cmd_coverage(args):
    subjects = _subjects(args)
    stats = taxonomy.load_library_stats(Path(args.library)) if args.library else {}
    lib_text = ""
    if args.library:
        lib_text = " ".join(t.text for s in subjects if s.source == "library" for t in s.topics)
    print(pipeline.coverage(Path(args.out), subjects, stats, lib_text), end="")


def cmd_brief(args):
    print(pipeline.briefs(Path(args.out), _subjects(args), args.subject, per_topic=args.per_topic), end="")


def cmd_corpus(args):
    n = pipeline.export_corpus(Path(args.out), Path(args.dest))
    print(f"wrote {n} lecture text files to {args.dest}")


def cmd_serve_media(args):
    from lecturelib import mediaserver

    root = Path(args.root)
    if not root.is_dir():
        sys.exit(f"media folder not found: {root}")
    mediaserver.serve(root, port=args.port, host=args.host)


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="cmd", required=True)

    def common(sp, need_library=False):
        sp.add_argument("--out", default="private/lectures", help="index folder (default: private/lectures)")
        sp.add_argument("--library", default=None if not need_library else ".", help="Ruled app folder (or its content/) to link rules")
        sp.add_argument("--no-florida", action="store_true", help="don't use the built-in Florida taxonomy")

    b = sub.add_parser("build", help="build or refresh the lecture index")
    common(b)
    b.add_argument("--transcripts", required=True, help="folder of .srt/.vtt/.json/.tsv/.txt transcripts (searched recursively)")
    b.add_argument("--media-root", help="folder of the videos, if not next to the transcripts")
    b.add_argument("--watch", type=int, metavar="SECONDS", help="keep running and refresh every N seconds")
    b.set_defaults(func=cmd_build)

    s = sub.add_parser("search", help="search lecture text")
    s.add_argument("query")
    s.add_argument("--out", default="private/lectures")
    s.add_argument("--subject", help="limit to one subject id, e.g. fl-wills")
    s.add_argument("--limit", type=int, default=10)
    s.add_argument("--json", action="store_true")
    s.set_defaults(func=cmd_search)

    c = sub.add_parser("coverage", help="lecture time vs. library content, as markdown")
    common(c)
    c.set_defaults(func=cmd_coverage)

    br = sub.add_parser("brief", help="authoring brief for one subject, as markdown")
    common(br)
    br.add_argument("subject", help="subject id, e.g. fl-wills or evidence")
    br.add_argument("--per-topic", type=int, default=12)
    br.set_defaults(func=cmd_brief)

    co = sub.add_parser("corpus", help="export plain text for the originality checker")
    co.add_argument("--out", default="private/lectures")
    co.add_argument("--dest", required=True)
    co.set_defaults(func=cmd_corpus)

    m = sub.add_parser("serve-media", help="serve videos with seeking support")
    m.add_argument("--root", required=True)
    m.add_argument("--port", type=int, default=4322)
    m.add_argument("--host", default="127.0.0.1")
    m.set_defaults(func=cmd_serve_media)

    args = p.parse_args(argv)
    args.func(args)


if __name__ == "__main__":
    main()
