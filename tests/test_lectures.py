"""Tests for tools/lectures.py and tools/lecturelib. Run: python3 -m unittest discover -s tests"""
from __future__ import annotations

import io
import json
import shutil
import sys
import tempfile
import threading
import unittest
import urllib.request
from contextlib import redirect_stdout
from http.server import ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))

from lecturelib import formats, mediaserver, pipeline, taxonomy, textutil  # noqa: E402
import lectures as cli  # noqa: E402

FIX = ROOT / "tests" / "fixtures"
TRANSCRIPTS = FIX / "transcripts"
LIBRARY = FIX / "library"


class FormatTests(unittest.TestCase):
    def test_timestamps(self):
        self.assertEqual(formats.parse_timestamp("01:02:03,450"), 3723.45)
        self.assertEqual(formats.parse_timestamp("02:03.4"), 123.4)
        self.assertEqual(formats.parse_timestamp("1:02:03"), 3723.0)
        with self.assertRaises(formats.TranscriptError):
            formats.parse_timestamp("soon")

    def test_srt(self):
        segs, timing, fmt = formats.read_transcript(TRANSCRIPTS / "Florida Wills" / "01 Intestacy and Elective Share.srt")
        self.assertEqual((timing, fmt), ("exact", "srt"))
        self.assertEqual(len(segs), 11)
        self.assertEqual(segs[1]["start"], 6.5)
        self.assertNotIn("-->", " ".join(s["text"] for s in segs))

    def test_vtt_rolling_captions_are_not_duplicated(self):
        segs, timing, _ = formats.read_transcript(TRANSCRIPTS / "Florida Civil Procedure" / "Lecture 3 - Proposals for Settlement.vtt")
        text = " ".join(s["text"] for s in segs)
        self.assertEqual(text.count("let's talk about proposals for settlement"), 1)
        self.assertEqual(text.count("the offer of judgment statute is 768.79"), 1)
        self.assertNotIn("NOTE", text)

    def test_whisper_json_and_whisper_cpp(self):
        segs, _, _ = formats.read_transcript(TRANSCRIPTS / "Evidence" / "hearsay-part1.json")
        self.assertEqual(len(segs), 6)
        self.assertEqual(segs[0]["text"][:7], "Hearsay")
        segs, _, _ = formats.read_transcript(TRANSCRIPTS / "Florida Wills" / "cpp" / "02 Will Execution.json")
        self.assertEqual([s["start"] for s in segs], [0.0, 8.0, 17.0])

    def test_tsv_skips_header(self):
        segs, _, _ = formats.read_transcript(TRANSCRIPTS / "Torts" / "comparative fault.tsv")
        self.assertEqual(len(segs), 5)
        self.assertEqual(segs[1]["start"], 9.0)

    def test_txt_with_and_without_stamps(self):
        segs, timing, _ = formats.read_transcript(TRANSCRIPTS / "Real Property" / "homestead.txt")
        self.assertEqual(timing, "exact")
        self.assertEqual(segs[2]["start"], 31.0)
        self.assertFalse(any("Homestead lecture" == s["text"] for s in segs))
        segs, timing, _ = formats.read_transcript(TRANSCRIPTS / "misc" / "untimed notes.txt")
        self.assertEqual(timing, "estimated")
        self.assertGreater(segs[-1]["end"], segs[0]["end"])

    def test_plain_whisper_text_json(self):
        segs, timing = formats.parse_json(json.dumps({"text": "One sentence here. Another one there."}))
        self.assertEqual(timing, "estimated")
        self.assertTrue(segs)

    def test_bad_json(self):
        with self.assertRaises(formats.TranscriptError):
            formats.parse_json("{nope")
        with self.assertRaises(formats.TranscriptError):
            formats.parse_json(json.dumps({"something": 1}))


class TextTests(unittest.TestCase):
    def test_stem_and_tokens(self):
        self.assertEqual(textutil.stem("parties"), "party")
        self.assertEqual(textutil.stem("witnesses"), "witness")
        self.assertEqual(textutil.stem("basis"), "basis")
        self.assertNotIn("the", textutil.tokens("The rule is the rule"))

    def test_tfidf_rank(self):
        model = textutil.TfIdf([textutil.terms("hearsay exception declarant"), textutil.terms("homestead forced sale devise")])
        top = model.rank(textutil.terms("is it hearsay"), top=1)
        self.assertEqual(top[0][0], 0)

    def test_clock(self):
        self.assertEqual(textutil.fmt_clock(65), "1:05")
        self.assertEqual(textutil.fmt_clock(3725), "1:02:05")


class PipelineTests(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.out = self.tmp / "out"

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _build(self, transcripts=TRANSCRIPTS, library=None, media_root=None):
        subjects = taxonomy.merged(library=library)
        with redirect_stdout(io.StringIO()):
            return pipeline.build(transcripts, self.out, subjects, media_root=media_root), subjects

    def test_discover_prefers_richer_format(self):
        found = [p.name for p in pipeline.discover(TRANSCRIPTS)]
        self.assertIn("hearsay-part1.json", found)
        self.assertNotIn("hearsay-part1.srt", found)

    def test_chunking_respects_target(self):
        segs = [{"start": i * 10.0, "end": i * 10.0 + 10, "text": f"Sentence {i}."} for i in range(30)]
        chunks = pipeline.chunk_segments(segs)
        self.assertTrue(all(c["end"] - c["start"] <= pipeline.MAX_CHUNK_SECONDS for c in chunks))
        self.assertEqual(sum(len(c["text"].split()) for c in chunks), 60)

    def test_build_tags_subjects_and_topics(self):
        manifest, _ = self._build()
        by_title = {l["title"]: l for l in manifest["lectures"]}
        self.assertEqual(by_title["01 Intestacy and Elective Share"]["subject"], "fl-wills")
        self.assertEqual(by_title["Hearsay Part1"]["subject"], "fl-evidence")
        self.assertEqual(by_title["Lecture 3 – Proposals for Settlement"]["topTopics"][0]["topic"], "fl-civil-procedure.sanctions-and-settlement")
        self.assertEqual(by_title["Homestead"]["topTopics"][0]["topic"], "fl-real-property.homestead")
        self.assertEqual(by_title["Untimed Notes"]["timing"], "estimated")
        self.assertEqual(manifest["errors"], [])
        links = json.loads((self.out / "links.json").read_text())
        self.assertIn("fl-wills.intestacy", links["topics"])

    def test_incremental_rebuild_and_stale_removal(self):
        work = self.tmp / "t"
        shutil.copytree(TRANSCRIPTS, work)
        self._build(work)
        n_files = len(list((self.out / "lectures").glob("*.json")))
        buf = io.StringIO()
        with redirect_stdout(buf):
            pipeline.build(work, self.out, taxonomy.merged())
        self.assertIn("0 processed", buf.getvalue())
        (work / "misc" / "untimed notes.txt").unlink()
        with redirect_stdout(io.StringIO()):
            manifest = pipeline.build(work, self.out, taxonomy.merged())
        self.assertEqual(len(list((self.out / "lectures").glob("*.json"))), n_files - 1)
        self.assertEqual(manifest["totals"]["lectures"], n_files - 1)

    def test_bad_file_is_skipped_not_fatal(self):
        work = self.tmp / "t"
        work.mkdir()
        (work / "broken.json").write_text("{not json")
        (work / "ok.txt").write_text("[00:00:00] Hearsay is an out of court statement.\n[00:00:05] Exceptions apply.\n")
        manifest, _ = self._build(work)
        self.assertEqual(manifest["totals"]["lectures"], 1)
        self.assertEqual(manifest["errors"][0]["path"], "broken.json")

    def test_media_found_next_to_transcript_and_in_media_root(self):
        work, media = self.tmp / "t", self.tmp / "videos"
        (work / "Wills").mkdir(parents=True)
        (media / "Wills").mkdir(parents=True)
        (work / "Wills" / "a.txt").write_text("[00:00:01] Intestate succession and heirs.\n[00:00:05] Per stirpes.\n")
        (work / "Wills" / "b.txt").write_text("[00:00:01] Elective share of thirty percent.\n[00:00:05] Elective estate.\n")
        (work / "Wills" / "a.mp4").write_bytes(b"x")
        (media / "Wills" / "b.mp4").write_bytes(b"x")
        manifest, _ = self._build(work, media_root=media)
        media_by_title = {l["title"]: l["media"] for l in manifest["lectures"]}
        self.assertEqual(media_by_title["A"], {"root": "transcripts", "path": "Wills/a.mp4"})
        self.assertEqual(media_by_title["B"], {"root": "media", "path": "Wills/b.mp4"})

    def test_library_rules_are_linked(self):
        manifest, subjects = self._build(library=LIBRARY)
        self.assertTrue(any(s.source == "library" for s in subjects))
        links = json.loads((self.out / "links.json").read_text())
        self.assertIn("evidence.hearsay-803.excited-utterance", links["rules"])

    def test_exam_tips_are_extracted_and_linked(self):
        self._build()
        links = json.loads((self.out / "links.json").read_text())
        tips = [t[3] for t in links["tips"].get("fl-wills.intestacy", [])]
        self.assertTrue(any(t.startswith("Remember too the slayer rule") for t in tips), tips)
        self.assertEqual(pipeline.exam_tips("Okay. So."), [])
        self.assertEqual(pipeline.exam_tips("The examiners love this trap on the exam every single time."),
                         ["The examiners love this trap on the exam every single time."])

    def test_florida_and_ube_twins_resolved_by_content(self):
        manifest, _ = self._build(library=LIBRARY)
        by_title = {l["title"]: l for l in manifest["lectures"]}
        # Folder "Evidence" names the UBE subject, but the lecture is about the Florida code.
        self.assertEqual(by_title["Hearsay Part1"]["subject"], "fl-evidence")
        lec = json.loads((self.out / "lectures" / f"{by_title['Hearsay Part1']['id']}.json").read_text())
        self.assertTrue(any(r["rule"].startswith("evidence.") for r in lec["chunks"][0]["rules"]))

    def test_search_coverage_brief_corpus(self):
        _, subjects = self._build(library=LIBRARY)
        hits = pipeline.search(self.out, "child victim hearsay")
        self.assertEqual(hits[0]["title"], "Hearsay Part1")
        report = pipeline.coverage(self.out, subjects, taxonomy.load_library_stats(LIBRARY), "hearsay")
        self.assertIn("# Lecture coverage report", report)
        self.assertIn("Wills & Administration of Estates", report)
        self.assertIn("surviving spouse", report)
        brief = pipeline.briefs(self.out, subjects, "fl-wills")
        self.assertIn("Elective share", brief)
        self.assertIn("@ 1:30", brief)
        n = pipeline.export_corpus(self.out, self.tmp / "corpus")
        self.assertEqual(n, len(list((self.tmp / "corpus").glob("*.txt"))))

    def test_cli_end_to_end(self):
        buf = io.StringIO()
        with redirect_stdout(buf):
            cli.main(["build", "--transcripts", str(TRANSCRIPTS), "--out", str(self.out)])
            cli.main(["search", "homestead devise", "--out", str(self.out), "--limit", "1"])
        self.assertIn("Homestead", buf.getvalue())


class MediaServerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = Path(tempfile.mkdtemp())
        (cls.tmp / "v").mkdir()
        (cls.tmp / "v" / "clip.mp4").write_bytes(bytes(range(256)) * 4)
        (cls.tmp / "secret.txt").write_text("outside")
        cls.httpd = ThreadingHTTPServer(("127.0.0.1", 0), mediaserver.make_handler(cls.tmp / "v"))
        cls.base = f"http://127.0.0.1:{cls.httpd.server_address[1]}"
        threading.Thread(target=cls.httpd.serve_forever, daemon=True).start()

    @classmethod
    def tearDownClass(cls):
        cls.httpd.shutdown()
        cls.httpd.server_close()
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def _get(self, path, headers=None):
        req = urllib.request.Request(self.base + path, headers=headers or {})
        try:
            with urllib.request.urlopen(req) as r:
                return r.status, dict(r.headers), r.read()
        except urllib.error.HTTPError as e:
            return e.code, dict(e.headers), b""

    def test_full_and_range(self):
        status, headers, body = self._get("/clip.mp4")
        self.assertEqual((status, len(body), headers["Accept-Ranges"]), (200, 1024, "bytes"))
        status, headers, body = self._get("/clip.mp4", {"Range": "bytes=10-19"})
        self.assertEqual((status, body, headers["Content-Range"]), (206, bytes(range(10, 20)), "bytes 10-19/1024"))
        status, _, body = self._get("/clip.mp4", {"Range": "bytes=-4"})
        self.assertEqual((status, body), (206, bytes(range(252, 256))))
        status, _, _ = self._get("/clip.mp4", {"Range": "bytes=5000-"})
        self.assertEqual(status, 416)

    def test_no_escape_or_listing(self):
        self.assertEqual(self._get("/../secret.txt")[0], 404)
        self.assertEqual(self._get("/%2e%2e/secret.txt")[0], 404)
        self.assertEqual(self._get("/")[0], 404)


if __name__ == "__main__":
    unittest.main()
