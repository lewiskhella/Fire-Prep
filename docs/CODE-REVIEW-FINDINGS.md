# Code review findings (add-on code)

From an adversarial review: 6 reviewers looked for bugs, then 3 independent skeptics tried to reproduce each finding.
It was stopped before its fix stage to save budget. Five of the confirmed findings were then fixed by hand and verified:

- **Fixed:** `--library .` loading every Florida subject twice. The library version (which has real rules) now absorbs the built-in keywords.
- **Fixed:** an upgrade of an older Florida install leaving `forTrackGuide` undefined. The Bench Book patch is now self-contained.
- **Fixed:** leaving the lecture reader resetting the saved position to 0 and the playback speed to 1.
- **Fixed:** non-UTF-8 transcripts decoding as UTF-16 garbage. UTF-16 is now used only when the file has a BOM.
- **Fixed:** one malformed transcript aborting the whole build. Every per-file error is now caught and reported.

Everything else below is still open.
Totals: 51 findings — 28 confirmed (2+ of 3 reproduced), 0 rejected, 23 not fully verified.

## Confirmed

### [high] With the Florida add-on installed, `--library .` loads every fl-* subject and topic twice. This duplicates tags, breaks twin resolution and duplicates the manifest and coverage entries.
- **File:** `tools/lecturelib/taxonomy.py`:171 (index)
- **Repro:** Run `python3 /tmp/claude-0/-home-user-Fire-Prep/e169ca09-de72-500f-ac94-fb779bdd7213/scratchpad/bh/r1.py`. It builds the test fixture transcripts with taxonomy.merged(library=<ruled-harness>); the harness has content/subjects/fl-* installed by install_florida.

Observed:
- 12 duplicate subject ids and 69 duplicate topic ids.
- index.json `subjects` has 26 entries but only 14 unique ids. For example, fl-wills appears twice: ('Wills & Administration of Estates','builtin') and ('Fl wills','library').
- 9 chunks carry the same topic twice in their top 3 tags, e.g. [fl-evidence.hearsay 0.683, evidence.hearsay-803, fl-evidence.hearsay 0.308]. The duplicate pushes a real secondary topic out of the top 3.
- 'Hearsay Part1' (a Florida-code lecture in folder Evidence) now gets subject 'evidence' (the UBE subject). With the fixture library it gets 'fl-evidence'. The cause: Tagger.subjects={s.id:s} lets the library fl-evidence overwrite the builtin one, so twins('evidence') finds no builtin twin.
- The coverage report prints every Florida subject twice ('## Wills & Administration…' and '## Fl wills').

Expected: one subject per id and one target per topic id, and the lecture filed as fl-evidence.
- **Proposed fix:** Change taxonomy.merged() to merge instead of concatenating. When a library subject id matches a builtin id, keep the builtin Subject (title, aliases, part, rulesSubject). For each library topic, take over a builtin topic with the same id by attaching its rules and appending its text (`bt.rules = lt.rules; bt.text += ' ' + lt.text`); otherwise append the topic. Append library-only subjects as today. I checked this in the scratch file fix1.py: it gives 14 unique subjects, 'Hearsay Part1' becomes fl-evidence, and 24 rule links remain. As a guard, Tagger.tag should also skip a topic id it has already added. For library-only subjects, take the title from content/catalog.json instead of _title_of(), which yields 'Fl wills'.
- **Verifier:** I reproduced it on my own file. tools/lecturelib/formats.py read_transcript tries ("utf-8-sig", "utf-16", "cp1252", "latin-1") in that order. Without a BOM, Python's utf-16 codec decodes nearly any even-length byte string without error, so cp1252 is never reached for those files. Repro: a 2-cue cp1252 SRT containing a curly apostrophe (U+2019). At 125 bytes it parses into 2 correct cues. Adding on

### [high] The incremental cache never refreshes `media`. A video added later, a newly passed `--media-root`, or a video moved away all leave a stale or null media reference.
- **File:** `tools/lecturelib/pipeline.py`:348 (index)
- **Repro:** Run `python3 /tmp/claude-0/-home-user-Fire-Prep/e169ca09-de72-500f-ac94-fb779bdd7213/scratchpad/bh/r2.py`.
- Build 1 runs without --media-root: media is None.
- Build 2 passes media_root: '0 processed, 1 unchanged', media still None.
- Build 3 runs after copying a.mp4 into the media root: still None.
- Build 4 runs after putting a.mp4 next to the transcript: still None.
- A fresh build of the same tree gives {'root': 'transcripts', 'path': 'Wills/a.mp4'}.

In the documented workflow (index while transcribing, add videos or --media-root later), 'play from here' never works until the transcript changes or the index is deleted. The reverse also holds: a deleted or moved video keeps a dead path.
- **Proposed fix:** In build(), recompute `lec['media'] = _media_ref(find_media(path, transcripts, media_root), transcripts, media_root)` for reused lectures (it is cheap). When the value changed, rewrite lec_file before building the entry. Alternatively, fold media_root and the resolved media path into the cache key.
- **Verifier:** I reproduced it by running /tmp/claude-0/-home-user-Fire-Prep/e169ca09-de72-500f-ac94-fb779bdd7213/scratchpad/bh/r5_json_crash.py against /home/user/Fire-Prep/tools. pipeline.build raised "AttributeError: 'list' object has no attribute 'get'" from process_lecture (pipeline.py:352), so no index.json was written and the valid Evidence/Hearsay.srt was not indexed. The per-file handler at pipeline.py:

### [high] Non-UTF-8 transcripts (cp1252, or one stray invalid byte) decode as UTF-16 garbage whenever the file has an even byte length
- **File:** `tools/lecturelib/formats.py`:228 (parsers)
- **Repro:** Script: /tmp/claude-0/-home-user-Fire-Prep/e169ca09-de72-500f-ac94-fb779bdd7213/scratchpad/bh/r1b.py. It builds a 2-cue SRT containing a curly apostrophe (’), encodes it as cp1252 (120 bytes, even) and runs read_transcript and pipeline.build. Observed: read_transcript returns ([], 'exact', 'srt'), and build reports errors=[{'path': 'Wills/01 Intestacy.srt', 'error': 'no text'}], lectures 0. Expected: 2 cues with text. The same file at 119 bytes (odd length) parses correctly. That is because utf-16 is tried before cp1252, and Python's utf-16 codec without a BOM accepts almost any even-length byte string. A .txt goes through the same path (r1_cp1252.py), so CJK garbage like '桔⁥整瑳瑡牯玒...' gets indexed as an 'estimated' lecture. r1c.py: a whisper.cpp JSON with one split multibyte byte (\xc3) parses at 163 bytes but at 164 bytes raises TranscriptError 'invalid JSON: Expecting value: line 1 column 1'.
- **Proposed fix:** Use utf-16 only when the file starts with a UTF-16 BOM: `encs = ("utf-16",) if raw[:2] in (b"\xff\xfe", b"\xfe\xff") else ("utf-8-sig", "cp1252", "latin-1")`. Optionally, when strict utf-8 fails on only a few bytes, prefer `raw.decode("utf-8", "replace")` over cp1252. Verified in a scratch copy: r1b/r1c then parse both lengths correctly and tests/test_lectures.py still passes.
- **Verifier:** I reproduced it. Running r1.py against the harness gives 12 duplicate subject ids (every fl-* id) and 69 duplicate topic ids. The manifest has 26 subjects but only 14 unique ids: fl-wills appears once as ('Wills & Administration of Estates', builtin) and again as ('Fl wills', library). 9 chunks carry the same topic twice in their top 3 tags, e.g. Hearsay Part1 has [fl-evidence.hearsay 0.683, evide

### [high] One malformed JSON transcript aborts the entire build (and the --watch loop) with an uncaught AttributeError/TypeError
- **File:** `tools/lecturelib/pipeline.py`:355 (parsers)
- **Repro:** Script: /tmp/claude-0/-home-user-Fire-Prep/e169ca09-de72-500f-ac94-fb779bdd7213/scratchpad/bh/r5_json_crash.py. The folder has a valid Evidence/Hearsay.srt plus Wills/Intestacy.json shaped like a pre-1.0 faster-whisper dump, where NamedTuple segments serialize as lists: {"segments": [[0,0,0.0,4.0," Intestate...",...]]}. Observed: pipeline.build raises `AttributeError: 'list' object has no attribute 'get'` from formats.parse_json line 137, so no index.json is written and the valid SRT is not indexed. More inputs that escape the `except (TranscriptError, OSError, UnicodeDecodeError, ValueError)` clause: {"segments":[{"start":null,...}]} gives TypeError float(None); whisper.cpp {"offsets":{"from":null}} gives TypeError; [{"text":"a","start":0},"oops"] gives AttributeError. Expected: the bad file is recorded in manifest['errors'] and the build continues.
- **Proposed fix:** In build(), widen the per-file handler to `except Exception as exc:` (or at least add TypeError, AttributeError, KeyError). In parse_json, skip entries that are not dicts (`if not isinstance(s, dict): continue`) and wrap float() and the offsets division so they raise TranscriptError.
- **Verifier:** I reproduced it. In build() (tools/lecturelib/pipeline.py around line 348), a lecture whose transcript sha1 has not changed is reloaded as-is from its cached lec_file, and `media` is never recomputed. The cache key is only the taxonomy signature plus the transcript sha1; media_root and the location of the video file are not part of it. Running r2.py: builds 2 to 4 (adding --media-root, copying a.m

### [high] Upgrading an existing Florida install breaks the Bench Book: content.js ends up calling forTrackGuide, which is never defined
- **File:** `tools/install_florida.py`:245 (installers)
- **Repro:** The harness already holds content.js as patched by an older installer (32271ce or earlier): the `forTrack` block, but no trackOf or forTrackGuide.
  S=/tmp/claude-0/-home-user-Fire-Prep/e169ca09-de72-500f-ac94-fb779bdd7213/scratchpad
  cp -a $S/ruled-harness "$S/ih/Bar Prep App"
  python3 tools/install_florida.py "$S/ih/Bar Prep App"
Output: `unchanged app/js/lib/content.js: already has jurisdiction track filter` and then `edited app/js/lib/content.js: Florida Bench Book sections`.
  grep forTrackGuide content.js -> only line 96: `export const guide = () => getJSON(...).then(forTrackGuide);` with no definition anywhere.
I served the copy, opened #/guide in Chromium and got: view `That page didn't load. forTrackGuide is not defined`, console `ReferenceError: forTrackGuide is not defined at guide (content.js:96)`.
The same happens on a clean upgrade. Run git 24a9fca's install_florida.py on a pristine copy, then HEAD's: `function forTrackGuide` count 0, `.then(forTrackGuide)` count 1.
The same cause also means the outlines.js marker `group === 'florida'` matches the older shelf patch, so the `Where Florida differs ->` link (fl-shelf-link) is never added on upgrade. grep florida/differences outlines.js -> 0, so the new page can't be reached.
The old forTrack also ignores catalog.examFlorida, so the exam profile never takes effect.
Expected: either a working upgrade or a SKIPPED warning, never a dangling reference.
- **Proposed fix:** Give each patch a marker for its current version, not a substring that older versions also contain. For content.js, use one Replace with done_marker "function forTrackGuide(" and two old->new pairs:
  (1) the previous CATALOG_NEW block (the 32271ce text, `function forTrack(cat) {...}`) -> current CATALOG_NEW, with CATALOG_OLD -> CATALOG_NEW as a fallback pair, i.e. try the pristine text and then the old patched text;
  (2) the guide line.
Then guide() is never rewritten unless the definition goes in with it.
For outlines.js, add an upgrade Replace with marker 'fl-shelf-link' that rewrites `h('span.count', fla.length)) : null,` to the version with the link.
- **Verifier:** I reproduced all three cases in the shared harness on port 4451. I served a 160 s WAV at the lecture's media path with `tools/lectures.py serve-media` on port 4452. The script is /tmp/claude-0/-home-user-Fire-Prep/e169ca09-de72-500f-ac94-fb779bdd7213/scratchpad/v343/r.js.

(a) and (b): I seeked to 90, played for 1.5 s, paused, set playbackRate=1.75 and waited 6 s. Prefs then read positions[id]=90 

### [high] Uninstall restores only the oldest backup set, so files first edited by a later run stay patched while the files they import are deleted
- **File:** `tools/installkit.py`:180 (installers)
- **Repro:** A. Harness as-is. Its oldest Florida stamp 170756 has no main.js, index.html or mbe.js; those were edited by later runs (173216, 173347).
  cp -a $S/ruled-harness $S/ih/U1 && python3 tools/install_florida.py $S/ih/U1 --uninstall
Result: fl-differences.js, florida.css and florida-plan.js are removed, but main.js:31 still has `route('/florida/differences', () => import('./views/fl-differences.js'))`, index.html:20 still links css/florida.css, and mbe.js still has flIds (3 hits).

B. Lectures, where the result is a crash. Make a pristine copy with S/ihtools/mkpristine.py, then:
  sed -i 's/rules.length ? list/rules.length > 0 ? list/' topic.js  (simulates the app changing)
  install_lectures.py  -> SKIPPED topic.js
  undo the sed, run install_lectures.py again  -> edited topic.js (backup goes into stamp 2)
  install_lectures.py --uninstall  -> restores only main/shell/index
topic.js still has `import { lectureAside } from '../ui/lecture-links.js'`, but lecture-links.js is gone. In Chromium, #/outlines/evidence/evidence.hearsay-definition renders an empty view with `404 app/js/ui/lecture-links.js` and `Failed to fetch dynamically imported module .../topic.js`. Every outline topic page is dead.
- **Proposed fix:** Build the restore set from all stamps, oldest first, and let the first backup of each path win. Skip any path that is under a CREATED entry, because those get removed. For example:
  originals={}
  for st in stamps:
    for f in sorted(st.rglob('*')):
      if f.is_file() and f.name!='CREATED.txt':
        rel=f.relative_to(st).as_posix()
        if rel not in originals and not any(rel==c or rel.startswith(c+'/') for c in created): originals[rel]=f
Then restore `originals`. I checked this on a harness copy: the Florida-related parts of app/ came back identical to pristine.
- **Verifier:** I confirmed this from the code and with a direct check. In app/js/views/lectures.js, lines 155, 201 and 208 build links as `?t=${Math.floor(start)}`. app/js/ui/lecture-links.js does the same at lines 30 and 34. The pipeline keeps chunk starts as fractional seconds rounded to 2 decimals (tools/lecturelib/pipeline.py:261). The reader turns query.t into startAt, and seek(t) calls passageAt(chunks, t 

### [high] Uninstall copies whole-file snapshots back, wiping the other add-on's patches and any edits made after install
- **File:** `tools/installkit.py`:192 (installers)
- **Repro:** Both installers patch app/js/main.js and app/index.html, and each restores its own full-file backup.
(1) The harness as-is (Lectures installed first, Florida later): `install_lectures.py <copy> --uninstall` gives grep -c florida main.js index.html -> 0 and 0, while fl-differences.js is still installed. The Florida route and stylesheet are gone, so the shelf link goes to Not Found.
(2) Pristine copy -> install_lectures -> install_florida -> install_lectures --uninstall (Florida routes and css gone) -> install_florida --uninstall. main.js again has route('/lectures'...) and index.html links css/lectures.css, but views/lectures.js and lectures.css have been deleted.
(3) Reverse order: pristine -> install_florida -> install_lectures -> install_florida --uninstall. main.js and index.html have 0 lectures lines, shell.js still shows the '§11 Lectures' nav entry, and that route now goes to Not Found.
(4) User data: install_florida, then append subject 'my-new-subject' to content/catalog.json and a line to welcome.js, then --uninstall. Both edits are silently gone (grep -> 0, 0), yet the tool prints 'Restored the files from before the first install.'
- **Proposed fix:** In each stamp, record the sha256 of every file as this run wrote it. On uninstall, copy the backup back only if the file still matches that hash. Otherwise undo the add-on's own edits in place and warn on any that fail:
  - InsertBefore/InsertAfterLine: remove `insert` once.
  - Replace: swap new->old.
  - TopicAside: remove the import line and `lectureAside(t),\n`.
  - catalog.json and guide.json: drop group 'florida' subjects, the examFlorida key and the florida-* sections.
This keeps the other add-on's patches and the user's own edits.
- **Verifier:** The code shows the defect directly. In readerView (app/js/views/lectures.js), the only replaceState call is at line 142, and it belongs to the list view. Nothing in the reader updates the hash during playback: the stamp buttons call seek() and the timeupdate handlers only mark passages and call savePosition. The topic pills and rule links are plain <a href> hash links, so clicking one adds a histo

### [high] Leaving the lecture reader resets the saved resume position to 0 and the playback speed to 1
- **File:** `app/js/views/lectures.js`:343 (views)
- **Repro:** I used a private harness copy at <scratchpad>/hunt-appjs/h, served on port 4391. A 160 s WAV was served by `tools/lectures.py serve-media --root <scratchpad>/hunt-appjs/media --port 4392`, the fl-wills 01 lecture's media.path was pointed at it, and prefs were set to mediaBase=http://127.0.0.1:4392/. Script: hunt-appjs/js/pos.js.
(a) Open #/lectures/florida-wills-01-intestacy-and-elective-share-60eee4, click the 1:30 stamp, play for 1.5 s, pause, wait 6 s, then set location.hash='#/lectures'. Observed: positions went from 90 (just after pausing) to 0 after leaving, and coming back starts the video at 0. Expected: 91.
(b) rate.js: set video.playbackRate=1.75, so prefs.rate=1.75, then leave. Observed: prefs.rate=1, and the lecture plays at 1 on return.
(c) pos2.js: with prefs positions={id:120} and the media server not running (or when you leave before metadata loads, or when the router throws away a stale render and calls destroy), open the lecture and leave. Observed: positions[id]=0, so the saved 120 is lost.
Cause: destroy() calls removeAttribute('src') and then load(). The load algorithm resets currentTime to 0 and playbackRate to the default, and fires timeupdate and ratechange into listeners that are still attached. The 5 s throttle has expired, so the timeupdate listener saves 0, and the ratechange listener saves rate 1. destroy() also calls savePosition(currentTime) even when no metadata ever loaded, so it saves 0.
Related, same symptom: lib/lectures.js:90 savePosition evicts keys[0], but updating an existing key does not move it to the end. Script evict.js: save 'favourite', then 199 others, then 'favourite' again, then one new id. The most recently watched 'favourite' gets evicted.
- **Proposed fix:** Add `let alive = true;` near the top of the reader. Guard both listeners: `if (!alive) return;` in the ratechange and timeupdate save handlers. In destroy() write: `alive = false; if (video) { if (video.readyState >= 1) savePosition(lec.id, video.currentTime); video.pause(); video.removeAttribute('src'); video.load(); }`. I checked this patch in my copy: pos.js keeps 91, pos2.js keeps 120, rate.js keeps 1.75. In savePosition, run `delete p.positions[lectureId]` before assigning, so the newest entry goes last.
- **Verifier:** The code confirms the defect. In app/js/ui/lecture-links.js, lines 23-24 build `rows` from the union of momentsFor(links, topic.id) and momentsFor(links, r.id) for each rule in topic.rules, keeping one row per lecture. Line 35 then shows "All ${rows.length} lectures →", linking to #/lectures?topic=<id>. That link opens momentsView in app/js/views/lectures.js (lines 183-199), which calls only momen

### [medium] If the transcripts folder disappears (for example an external drive unmounted during `build --watch`), every lecture file is deleted and the index is rewritten with 0 lectures.
- **File:** `tools/lecturelib/pipeline.py`:340 (index)
- **Repro:** Run `python3 /tmp/claude-0/-home-user-Fire-Prep/e169ca09-de72-500f-ac94-fb779bdd7213/scratchpad/bh/r4.py`, which builds from 'Volumes/Extreme Pro', renames the folder away, then rebuilds.
- Output: 'before: 7 lecture files: 7', then 'lectures: 0 indexed (0 processed, 0 unchanged), 0 skipped' and 'after: 0 lecture files: 0'.
- After remounting, all 7 lectures are reprocessed from scratch.
- Python 3.11 behaves the same.

cmd_build only checks is_dir() once, before the watch loop, and build() itself never checks it. discover() on a missing folder returns [], and the stale sweep then unlinks everything. Meanwhile the app serves an empty Lectures section.

Expected: the build refuses to run, or at least does not delete anything, when the root is missing.
- **Proposed fix:** At the top of pipeline.build(), add `if not transcripts.is_dir(): raise FileNotFoundError(...)`. In cmd_build's watch loop, catch that error, log it and sleep instead of exiting. Optionally skip the stale sweep when `found` is empty but `old` was not.
- **Verifier:** I reproduced this against /home/user/Fire-Prep/tools/lecturelib/formats.py. I ran parse_txt on "[00:00.000 --> 00:05.200]  Today we cover the hearsay rule.\n[00:05.200 --> 00:11.000]  Hearsay is ..." and it returned segments with text '-> 00:05.200] Today we cover the hearsay rule.' and '-> 00:11.000] Hearsay is an out of court statement.'. The cause is in _TXT_STAMP (line 35): `^\s*[\[(]?\s*{_TS}

### [medium] The taxonomy signature hashes only topic id and text. Renaming rule ids or changing aliases, subject titles or rulesSubject never invalidates cached lectures.
- **File:** `tools/lecturelib/pipeline.py`:236 (index)
- **Repro:** First repro: run `python3 /tmp/claude-0/-home-user-Fire-Prep/e169ca09-de72-500f-ac94-fb779bdd7213/scratchpad/bh/r3.py`. It renames every rule id in the library outline (text unchanged) and rebuilds.
- Output: '0 processed, 7 unchanged'.
- links.json still lists 'evidence.hearsay-803.business-records', 'evidence.hearsay-803.excited-utterance' and 'evidence.hearsay-definition.what-counts'. None of these exist any more, so the app's rule links break.
- Rule text comes from _strings(), which skips 'id', so topic.text does not change.

Second repro: run `python3 /tmp/claude-0/-home-user-Fire-Prep/e169ca09-de72-500f-ac94-fb779bdd7213/scratchpad/bh/r3b.py`, which adds the alias 'misc' to fl-wills.
- Cached result: ('fl-torts','content').
- Fresh build: ('fl-wills','name').

The subject title is also part of the TF-IDF documents but is not hashed.
- **Proposed fix:** In _signature, also hash for each subject: s.id, s.title, the sorted aliases, s.rules_subject and s.source. For each topic, hash the keywords and every rule id plus rule text. Separate fields with a delimiter such as '\0'.
- **Verifier:** I reproduced this against /home/user/Fire-Prep/tools. With 'Evidence/Lecture 1.wav' + 'Lecture 1.wav.srt', and 'Lecture 2.mp4' + 'Lecture 2.en.vtt' + 'Lecture 2.json', discover() returned all three transcripts. That happens because pipeline.py:74 builds its key with p.with_suffix(""), which keeps '.wav' and '.en' in the key. build() then produced three lectures: 'Lecture 1.wav' with media None, 'L

### [medium] One malformed transcript (or a non-UTF-8 filename) aborts the whole build because the error handling catches only a narrow set of exceptions.
- **File:** `tools/lecturelib/pipeline.py`:355 (index)
- **Repro:** First repro: run `python3 /tmp/claude-0/-home-user-Fire-Prep/e169ca09-de72-500f-ac94-fb779bdd7213/scratchpad/bh/r5.py`. Each case pairs a good .txt with a bad .json.
- {"segments":[{"text":"…","start":null}]} raises TypeError.
- {"segments":["…"]} raises AttributeError.
- whisper.cpp offsets given as strings raise TypeError.
- [{"text":"…"},"oops"] raises AttributeError.
- In every case the whole build aborts. No manifest is written and a --watch loop dies, even though test_bad_file_is_skipped_not_fatal says bad files must be skipped.

Second repro: run `python3 /tmp/claude-0/-home-user-Fire-Prep/e169ca09-de72-500f-ac94-fb779bdd7213/scratchpad/bh/r8.py`. A file named b'x/caf\xe9.txt' makes lecture_id(), which runs outside the try at line 346, raise UnicodeEncodeError ('surrogates not allowed'), and the build aborts.
- **Proposed fix:** Move the `lec_file = … lecture_id(...)` line inside the try. Catch Exception per file (or add TypeError, AttributeError, KeyError and UnicodeError) and record it in `errors`. In formats.parse_json, skip non-dict segments and coerce `start`/`end` with `float(x or 0)`.
- **Verifier:** I reproduced it against /home/user/Fire-Prep/tools/lecturelib/formats.py. _dedupe_rolling uses `seg["text"].startswith(prev)` and then slices `seg["text"][len(prev):]`. That is a character-prefix test with no word-boundary check, so it splits words.

- Word-level SRT (So, Some, courts, ..., therefore, ..., answer, in, intestacy, a, and) parses to 'So me courts say the refore clause is an swer in t

### [medium] A corrupt or half-written cached lecture file makes a valid transcript appear as a skipped error and be dropped from the index. Writes are not atomic.
- **File:** `tools/lecturelib/pipeline.py`:349 (index)
- **Repro:** Run `python3 /tmp/claude-0/-home-user-Fire-Prep/e169ca09-de72-500f-ac94-fb779bdd7213/scratchpad/bh/r6.py`. It truncates one lectures/<id>.json, as Ctrl-C during write_text in --watch would, then rebuilds.
- Output: 'lectures: 6 indexed (0 processed, 6 unchanged), 1 skipped'.
- errors=[{'path': 'Florida Civil Procedure/Lecture 3 - Proposals for Settlement.vtt', 'error': 'Expecting property name…'}].
- The lecture file is then deleted, so the lecture is missing until a third build.

Expected: the build detects the bad cache and reprocesses the transcript.

index.json and links.json are also written with plain write_text, so the app can fetch a half-written file during --watch.
- **Proposed fix:** Wrap the cached load in its own try. On JSONDecodeError or OSError, fall through to process_lecture() instead of recording an error. Write every output through a helper: write to `<name>.tmp`, then `os.replace(tmp, final)`.
- **Verifier:** I reproduced all three cases against /home/user/Fire-Prep/tools/lecturelib/pipeline.py (TARGET=75 s, MAX=150 s). (a) An untimed .txt of 600 unpunctuated lines goes through parse_txt as 1 estimated segment of 2880 s, and chunk_segments returns 1 chunk of 2880 s. With 10-minute stamps the chunks are 600 s each. (b) Segments at 0-10 s and 910-920 s come out as a single 0-920 s chunk. The 0-915 varian

### [medium] guess_subject_from_name picks the longest alias anywhere in the path, and that name match overrides content. A torts lecture whose filename mentions 'evidence' is filed under Evidence.
- **File:** `tools/lecturelib/pipeline.py`:217 (index)
- **Repro:** Run `python3 /tmp/claude-0/-home-user-Fire-Prep/e169ca09-de72-500f-ac94-fb779bdd7213/scratchpad/bh/r14.py`. The file is 'Torts/Res ipsa loquitur - circumstantial evidence.srt' and its content is entirely negligence and comparative fault.
- Builtin taxonomy only: subject fl-torts.
- With the fixture library: subject 'evidence', subjectSource 'name', while topTopics is [fl-torts.negligence-and-fault 80 s].
- The cause: the library alias ' evidence ' (10 chars) beats ' tort ' (6 chars) and wins over the folder name. Twins are only consulted for the guessed subject (evidence/fl-evidence), and both have 0 s of content, so 'evidence' stays.
- **Proposed fix:** Match the folder parts first, from deepest to shallowest, and fall back to the file stem only when no folder matches. Either:
- `for part in reversed(rel.parent.parts): hit = best_alias(part); if hit: return hit`, then the stem; or
- in process_lecture, ignore a filename-only guess when by_content has at least half of the tagged seconds and is not the guess or one of its twins.
- **Verifier:** I reproduced it. Running /tmp/claude-0/-home-user-Fire-Prep/e169ca09-de72-500f-ac94-fb779bdd7213/scratchpad/bh/r4_ws_line.py against /home/user/Fire-Prep/tools prints only two segments: {start 3.0, end 3.01, 'welcome to evidence'} and {start 3.01, end 6.0, 'today hearsay'}. The cues at 00:20:00 and 00:20:10 are lost completely, and 'welcome to evidence' starts at 3.0 when it should start at 0.0. T

### [medium] When the preferred format for a lecture fails to parse, the lecture is skipped even though a valid sibling transcript (e.g. .srt) exists.
- **File:** `tools/lecturelib/pipeline.py`:61 (index)
- **Repro:** Run `python3 /tmp/claude-0/-home-user-Fire-Prep/e169ca09-de72-500f-ac94-fb779bdd7213/scratchpad/bh/r10.py`. The folder holds a good Hearsay.srt and a Hearsay.json that is a metadata sidecar (the same happens with a half-written whisper JSON).
- Output: 'lectures: 0 indexed …, 1 skipped'.
- errors=[{'path':'Hearsay.json','error':"JSON has no 'segments'…"}].
- The valid SRT is never tried, because discover() keeps only the top-ranked file per stem.

Expected: the lecture is indexed from Hearsay.srt.
- **Proposed fix:** Have discover() return, for each stem, the candidates ordered by rank. In build(), try each candidate in order and use the first one that parses into at least one chunk; only when all fail, record the first error. The cache key can stay keyed by the chosen candidate's rel path.
- **Verifier:** I reproduced it against the repo code in /home/user/Fire-Prep/tools/lecturelib/formats.py. The test script loads it through common.py, which puts /home/user/Fire-Prep/tools on sys.path. parse_txt returned 'exact' with two segments, starting at 540.0 ('in the morning ...') and 630.0 ('the defendant calls his lawyer.'). Words in: 77, words out: 34. The code shows why. Any line matching _TXT_STAMP co

### [medium] Whisper / whisper.cpp console-format TXT ("[00:00.000 --> 00:05.200]  text") leaks '-> 00:05.200]' into every segment and drops the end time
- **File:** `tools/lecturelib/formats.py`:35 (parsers)
- **Repro:** Script: /tmp/claude-0/-home-user-Fire-Prep/e169ca09-de72-500f-ac94-fb779bdd7213/scratchpad/bh/r2_whisper_stdout.py. It runs parse_txt on the output of `whisper x.mp3 > x.txt` ("[00:00.000 --> 00:05.200]  Today we cover the hearsay rule.") and on whisper.cpp stdout ("[00:00:00.000 --> 00:00:05.200]   ..."). Observed: text = '-> 00:05.200] Today we cover the hearsay rule.' and '-> 00:00:05.200] Today...'. In _TXT_STAMP, `[-–:]?` eats the first '-' of '-->' and the rest goes into the text. The junk tokens also inflate word counts and the estimated end of the last segment (15.0 instead of 15.5). Expected: clean text, with end taken from the second stamp.
- **Proposed fix:** Allow an optional end stamp in _TXT_STAMP: `rf"^\s*[\[(]?\s*{_TS}(?:\s*-->\s*{_TS})?\s*[\])]?\s*[-–:]?\s*(.*)$"`. Read the text from m.group(9), and when groups 5-8 are set, use them as the segment end. Verified in a scratch copy: the text comes out clean and existing tests pass.
- **Verifier:** I reproduced it. Running the repro script printed "before: 7 lecture files: 7", then "lectures: 0 indexed (0 processed, 0 unchanged), 0 skipped", then "after: 0 lecture files: 0". After the folder was restored, the next build printed "7 indexed (7 processed, 0 unchanged)", so every lecture was rebuilt from scratch. The code matches what the reviewer described. In tools/lectures.py, cmd_build (line

### [medium] Transcripts named '<video>.<mediaext>.<ext>' (whisper.cpp default) or '<video>.en.vtt' (yt-dlp) get no media link, a bad title, and duplicate lectures
- **File:** `tools/lecturelib/pipeline.py`:89 (parsers)
- **Repro:** Script: /tmp/claude-0/-home-user-Fire-Prep/e169ca09-de72-500f-ac94-fb779bdd7213/scratchpad/bh/r6_cpp_names.py. Files: 'Evidence/Lecture 1.wav' + 'Lecture 1.wav.srt' (whisper.cpp writes <input filename>.srt/.json/.txt by default), and 'Lecture 2.mp4' + 'Lecture 2.en.vtt' + 'Lecture 2.json'. Observed: discover returns all three transcripts. Results: title 'Lecture 1.wav' with media None, although the media file sits next to it (find_media looks for 'Lecture 1.wav.mp4' etc.); 'Lecture 2' with media found; 'Lecture 2.en' with media None, which is the same lecture indexed twice. Related title_from_path defect (r9_title.py): its `\s*[-–]\s*` rewrite also hits in-word hyphens, so 'Lecture 4 - Pre-trial Motions and Non-final Appeals' becomes 'Lecture 4 – Pre – trial Motions and Non – final Appeals', 'Self-proving affidavits' becomes 'Self – proving affidavits', and "testator's intent and anti-lapse" becomes "Testator'S Intent And Anti – Lapse".
- **Proposed fix:** Add a `_base_stem(p)` helper that drops one inner suffix when it is a media extension (formats.MEDIA_EXTS) or a language tag (`\.[a-z]{2,3}(-[A-Za-z]{2,4})?`). Use it for the discover() key, in find_media (also try `d / transcript.stem` itself when its suffix is a media extension), and in title_from_path. In title_from_path, rewrite only spaced dashes with `re.sub(r"\s+[-–]\s+", " – ", stem)`, and title-case with `re.sub(r"[A-Za-z]+('[a-z]+)?", lambda m: m.group(0).capitalize(), stem)` instead of str.title().
- **Verifier:** The defect is real: I reproduced it.

**First repro:** I ran `scratchpad/bh/r3.py` against the current code and got the reported result. The first build said '7 processed, 0 unchanged'. After every rule id in the evidence outline was renamed, the rebuild said '0 processed, 7 unchanged'. `links.json` still lists `evidence.hearsay-803.business-records`, `evidence.hearsay-803.excited-utterance` and `

### [medium] Rolling-caption dedupe cuts at character prefixes (corrupting words) and merges identical cues regardless of time gap
- **File:** `tools/lecturelib/formats.py`:109 (parsers)
- **Repro:** Script: /tmp/claude-0/-home-user-Fire-Prep/e169ca09-de72-500f-ac94-fb779bdd7213/scratchpad/bh/r3_prefix.py. Word-level SRT (whisper.cpp -ml 1 / --max_words_per_line 1) with cues So, Some, courts, say, the, therefore, clause, is, an, answer, in, intestacy, a, and. Observed text: 'So me courts say the refore clause is an swer in testacy a nd'. A phrase SRT with cues 'In' then 'Indiana the rule differs.' gives ['In', 'diana the rule differs.']. r3b.py: two 'Objection.' cues at 0:01 and 5:00 collapse into one segment {'start': 1.0, 'end': 301.0}, which loses the second utterance and creates a 5-minute segment.
- **Proposed fix:** Compare at word level: `pw, sw = prev.split(), seg["text"].split(); if len(pw) <= len(sw) and sw[:len(pw)] == pw: rest = " ".join(sw[len(pw):])`. As a minimum, require `not seg["text"][len(prev):len(prev)+1].isalnum()`. Merge exact-equal cues only when they overlap or touch: `seg["start"] - out[-1]["end"] <= 1.0`. Verified in a scratch copy that the word-boundary check fixes r3_prefix and keeps the rolling-VTT fixture test passing.
- **Verifier:** I reproduced both cases against /home/user/Fire-Prep/tools/lecturelib/pipeline.py. In pipeline.build, the per-file try catches only (formats.TranscriptError, OSError, UnicodeDecodeError, ValueError). The `lec_file = ... lecture_id(Path(rel))` line runs before that try.

r5.py: each of the four malformed .json files sat next to a good .txt, and each one aborted the whole build. No manifest was writ

### [medium] chunk_segments makes chunks far longer than MAX_CHUNK_SECONDS: one chunk for a whole unpunctuated TXT lecture, and chunks that span long silences
- **File:** `tools/lecturelib/pipeline.py`:126 (parsers)
- **Repro:** Scripts: /tmp/claude-0/-home-user-Fire-Prep/e169ca09-de72-500f-ac94-fb779bdd7213/scratchpad/bh/r7_giant_chunk.py, r11_gap.py and r11b_build.py. (a) An untimed .txt of 600 unpunctuated lines, no blank lines (~48 min). parse_txt makes it 1 segment (whole file is one paragraph with no sentence breaks), so chunk_segments returns 1 chunk of 2880 s. Search, 'play from here' and tagging then treat the whole lecture as one passage. Stamped TXT with 10-minute spacing gives 600 s chunks. (b) An SRT with speech at 0-10 s and 910-915 s yields one chunk 0-920 s mixing both parts. The gap flush is missing, and the short-tail fold then glues across the gap. In a build, topTopics reports {'topic':'fl-real-property.homestead','seconds':915.0} for 15 s of speech. (c) 14 x 10 s segments + one 40 s cue gives a 180 s chunk (max is 150).
- **Proposed fix:** In chunk_segments: before `cur.append(seg)`, `flush()` when `cur and (seg['start'] - max(s['end'] for s in cur) > 30 or seg['end'] - cur[0]['start'] > maximum)`. Pre-split any segment longer than `target` into word windows with interpolated times. Fold the tail only when `chunks[-1]['start'] - chunks[-2]['end'] <= 30`, and use `max()` for the folded end. Verified in a scratch copy: (a) becomes 25 chunks of about 114 s, (b) becomes 0-10 and 910-920, and tests/test_lectures.py passes.
- **Verifier:** I reproduced it. Running r6.py against tools/lecturelib/pipeline.py gives 'lectures: 6 indexed (0 processed, 6 unchanged), 1 skipped'. It records an error for 'Florida Civil Procedure/Lecture 3 - Proposals for Settlement.vtt' ('Expecting property name enclosed in double quotes...'), and afterwards the lecture file no longer exists. The code shows why. When the index entry and the transcript sha1 s

### [medium] A whitespace-only line ends a cue, so YouTube-style VTT cues starting with a ' ' line lose their text (or are mis-timed)
- **File:** `tools/lecturelib/formats.py`:78 (parsers)
- **Repro:** Script: /tmp/claude-0/-home-user-Fire-Prep/e169ca09-de72-500f-ac94-fb779bdd7213/scratchpad/bh/r4_ws_line.py. A YouTube auto-caption VTT where the first payload line of a cue is a single space (the empty upper row), followed by 'welcome<00:00:00.500><c> to</c>...'. Observed: [{'start': 3.0, 'end': 3.01, 'text': 'welcome to evidence'}, {'start': 3.01, 'end': 6.0, 'text': 'today hearsay'}]. The cues at 00:20:00 ('after the break privileges') and 00:20:10 ('spousal privilege rules') are lost entirely, and the first line is timed 3 s late (taken from the 10 ms repeat cue). The `lines[i].strip()` loop condition stops the body at ' ', but WebVTT only ends a cue on an empty line.
- **Proposed fix:** End the cue body only on a truly empty line: `while i < n and lines[i] != "" and not _CUE.match(lines[i]):`. The existing trailing-sequence-number pop plus clean_text already handle SRT separators made of spaces. Verified in a scratch copy: all 4 cues are recovered with correct starts, the SRT case with a '   ' separator still parses, and tests pass.
- **Verifier:** I reproduced the defect. Running r14.py against the current code gives:
- builtin -> fl-torts, source name
- library -> evidence, source name, with topTopics [fl-torts.negligence-and-fault 80s]

The code shows why. In pipeline.py:217, guess_subject_from_name joins every path part (folder plus file stem) into one string and keeps the longest alias it finds anywhere. With the library taxonomy, the a

### [medium] Untimed TXT whose wrapped lines happen to start with a clock time is treated as 'exact', and all text before that line is dropped
- **File:** `tools/lecturelib/formats.py`:187 (parsers)
- **Repro:** Script: /tmp/claude-0/-home-user-Fire-Prep/e169ca09-de72-500f-ac94-fb779bdd7213/scratchpad/bh/r8_txt_preamble.py. Hard-wrapped untimed notes where one line begins '9:00 in the morning...' and a later one '10:30 the defendant...'. Observed: timing 'exact', segments start at 540.0 and 630.0, and 'words in: 77 words out: 34'. The first three lines, which come before the first 'stamp', are discarded, because parse_txt only appends continuation lines once `stamped` is non-empty and accepts any 2 monotonic stamps.
- **Proposed fix:** Trust stamps only when they look like a timed transcript. For example, compute `nonblank` lines and the index of the first stamped one, and take the exact branch only if `first <= 2 and stamped_lines * 4 >= len(nonblank)`; otherwise fall back to the estimated path. Verified in a scratch copy: the repro becomes 'estimated' with all 77 words, and the homestead.txt fixture (header + 8 stamped lines) stays exact.
- **Verifier:** I reproduced it. Running r10.py prints "lectures: 0 indexed (0 processed, 0 unchanged), 1 skipped", records the error [{'path': 'Hearsay.json', 'error': "JSON has no 'segments', 'transcription' or 'text' field"}], and indexes no lectures, even though Hearsay.srt next to it is valid. The code shows why. discover() in tools/lecturelib/pipeline.py (lines 61-78) builds a best dict keyed by p.with_suff

### [medium] Backup sets are named in local time, so after a timezone or DST change uninstall treats a later run as the original
- **File:** `tools/installkit.py`:109 (installers)
- **Repro:** Pristine copy "$S/ih/TZ test":
  TZ=America/New_York python3 tools/install_lectures.py "$T"
  TZ=America/Los_Angeles python3 tools/install_lectures.py "$T"   (the re-run reports all 4 patches unchanged)
  ls .lectures-backup -> 20261102-100301 (second run) sorts before 20261102-130301 (first run)
  python3 tools/install_lectures.py "$T" --uninstall
It restores only add-on files (the second run's copies) and removes them. main.js still has both /lectures routes, shell.js the nav entry, index.html the css link, and topic.js the static import of the deleted lecture-links.js, so topic pages break as in the previous finding.
The same thing happens when you re-run within the hour after the fall-back DST change (e.g. 01:50 EDT, then 01:20 EST), or after travelling west.
- **Proposed fix:** Order backup sets by a monotonic key that doesn't depend on the clock. For example, name them `f"{n:04d}-" + time.strftime('%Y%m%d-%H%M%S', time.gmtime())`, where n = 1 + the largest existing prefix, and sort on n. At minimum, use time.gmtime() for the stamp.
- **Verifier:** Reproduced in the harness with Playwright. On #/lectures I set input.lec-search to 'homestead', fired an input event and set location.hash='#/plan' in the same tick. After 1.2 s, location.hash was '#/lectures?q=homestead' while the Calendar view was showing and the lecture search input was gone from the DOM. Going back then landed on '#/lectures', so the #/plan history entry had been replaced. The

### [medium] CREATED.txt is written only at the end, so an interrupted install's new files are never recorded and uninstall leaves the app half-installed
- **File:** `tools/installkit.py`:168 (installers)
- **Repro:** S/ihtools/interrupt.py runs install_lectures.main on a pristine copy and raises KeyboardInterrupt (as Ctrl-C or ejecting the exFAT drive would) right after the 2nd patched file is written. All files are copied by then, main.js and shell.js are edited, and no CREATED.txt exists.
Then `install_lectures.py` (index.html and topic.js edited; the lecture files now exist, so they are not 'created') and `install_lectures.py --uninstall`.
Uninstall prints no 'remove' lines. views/lectures.js, ui/lecture-links.js and tools/lecturelib all remain, and topic.js and index.html stay patched, yet it reports 'Restored the files from before the first install.'
- **Proposed fix:** In install(), when not dry: create stamp_dir before the copy loop, and append each dst_rel to CREATED.txt (open in 'a' mode and flush) before copying it. Don't collect the list in memory and write it at the end. Optionally write a COMPLETE marker at the end and warn on uninstall when it is missing.
- **Verifier:** The defect is real. I confirmed it by reading the code; I did not run the browser repro. In tools/lecturelib/pipeline.py (lines 269-287), `subject = named or by_content` comes out None when neither the file name nor the content matches a subject. In app/js/views/lectures.js libraryView (about lines 98-140), such lectures are grouped under `l.subject || ''`, so `order` holds a '' entry, sorted last

### [low] links.json exam tips are not ranked: a topic keeps the first 12 tips in alphabetical lecture order. Strong tips are dropped, and outline pages show weak ones.
- **File:** `tools/lecturelib/pipeline.py`:424 (index)
- **Repro:** Run `python3 /tmp/claude-0/-home-user-Fire-Prep/e169ca09-de72-500f-ac94-fb779bdd7213/scratchpad/bh/r11.py`. Seven lectures 'A0..A6 Intestacy' each carry two weak 'remember / make sure' tips. 'Z Intestacy Review' carries 'The bar examiners love to test this trap on the Florida exam…', which scores about 8 versus 2 or 3.
- Output: '12 tips kept; Z lecture present: False'.
- The first two tips, which lecture-links.js shows on outline and rule pages via .slice(0,2), are both from 'A0 Intestacy'.
- The cause: build_links appends tips in manifest order and truncates with `v[:12]`. The score from exam_tips is thrown away.
- **Proposed fix:** Have exam_tips also return the score, or recompute it with the cue weights. In build_links, sort each topic's tips by score descending, keep at most 2 per lecture, then cap at 12.
- **Verifier:** I reproduced it against the repo code at /home/user/Fire-Prep/tools: the reviewer's script imports from there through common.py. A JSON list of 200 {speaker, text} paragraphs gives `exact 200 segs -> 1 chunk(s) [(0.0, 0.0, 3400)]`. The code shows why. In formats.py, `parse_json`'s segments branch (lines 134-139) sets start and end to `s.get("start", 0.0)` and labels the timing "exact" without chec

### [low] chunk_segments never splits a single oversized segment. An untimed transcript without punctuation becomes one huge passage, and folding a short tail can shrink a chunk's end time.
- **File:** `tools/lecturelib/pipeline.py`:115 (index)
- **Repro:** Run `python3 /tmp/claude-0/-home-user-Fire-Prep/e169ca09-de72-500f-ac94-fb779bdd7213/scratchpad/bh/r12.py`.
- A 1860-word .txt with no punctuation becomes 1 chunk lasting 744 s, against MAX_CHUNK_SECONDS = 150. The whole lecture gets a single tag set, one search hit and one 'play from here' point.
- The same script calls chunk_segments([{0-200 'Long cue.'},{190-195 'Short tail.'}]) and gets end=195, although the merged text runs to 200, because the tail fold assigns `chunks[-1]['end'] = tail['end']` instead of max().
- **Proposed fix:** Before chunking, split any segment longer than MAX_CHUNK_SECONDS into word slices of about TARGET_CHUNK_SECONDS, giving each slice a time span in proportion to its share of the words. In the tail fold, use `chunks[-1]['end'] = max(chunks[-1]['end'], tail['end'])`.
- **Verifier:** I reproduced this against the repo code at /home/user/Fire-Prep/tools/lecturelib/formats.py. The tag pattern is `_TAG = re.compile(r"<[^>]+>")`, so it deletes everything from any '<' to the next '>'. clean_text then decodes entities with a fixed chain: &nbsp;, then &amp;, then &lt;, then &gt;. Results:
- clean_text('If the amount is < $15,000 it goes to county court, and if > $50,000 circuit court

### [low] JSON segments without timestamps are labelled 'exact' and collapse into one zero-length chunk holding the whole lecture
- **File:** `tools/lecturelib/formats.py`:134 (parsers)
- **Repro:** Script: /tmp/claude-0/-home-user-Fire-Prep/e169ca09-de72-500f-ac94-fb779bdd7213/scratchpad/bh/r13_json_notime.py. A JSON list of 200 {"speaker":..., "text":...} paragraphs with no start/end. Observed: `exact 200 segs -> 1 chunk(s) [(0.0, 0.0, 3400)]`. Every start and end defaults to 0, so chunk duration never grows and everything flushes as one chunk. Lecture duration is 0 and timing is falsely 'exact'.
- **Proposed fix:** In the segments branch of parse_json, if no segment has a 'start' key (or every start and end is 0), return `parse_txt("\n\n".join(texts))` to get estimated timing instead of 'exact' zeros.
- **Verifier:** I reproduced the defect. In build_links (tools/lecturelib/pipeline.py, around lines 405-424), tips are added to each topic in manifest (lecture) order, and the result is cut with `{k: v[:12]}`. Nothing sorts them by score first, and exam_tips (line 45) drops the score it computed. Running r11.py printed '12 tips kept; Z lecture present: False'. The first two kept tips were both weak 'Make sure / R

### [low] clean_text deletes everything between a '<' and a later '>' in plain text, and decodes entities incompletely and twice
- **File:** `tools/lecturelib/formats.py`:36 (parsers)
- **Repro:** Script: /tmp/claude-0/-home-user-Fire-Prep/e169ca09-de72-500f-ac94-fb779bdd7213/scratchpad/bh/r12_clean.py. clean_text('If the amount is < $15,000 it goes to county court, and if > $50,000 circuit court.') gives 'If the amount is $50,000 circuit court.'. Whisper JSON text ' Damages < $8,000 go to small claims; the rest > that go elsewhere.' gives 'Damages that go elsewhere.'. '{\\an8}It&#39;s the &quot;mailbox rule&quot;.' is left unchanged (SRT position tag and numeric/quote entities kept). 'A &amp;lt; B' gives 'A < B' (double unescape).
- **Proposed fix:** Restrict _TAG to real caption markup: `re.compile(r"</?[A-Za-z][^<>]*>|<\d+:\d{2}[:.,\d]*>|\{\\[^{}]*\}")`, and replace the manual replace chain with `html.unescape(text).replace("\xa0", " ")`. Verified in a scratch copy: the outputs are the full sentences, "It's the \"mailbox rule\"." and 'A &lt; B', and the VTT fixture tests still pass.
- **Verifier:** I reproduced both claims by running r12.py against the current code.

1. An 1860-word untimed .txt with no punctuation became 1 chunk lasting 744 s, against MAX_CHUNK_SECONDS = 150. chunk_segments (tools/lecturelib/pipeline.py around line 115) only flushes once a group of segments reaches the limit. It never splits a single segment, so the whole lecture becomes one chunk. That gives the lecture on

### [low] Re-installing doesn't refresh: files and subjects removed from the pack stay in the app and in the catalog
- **File:** `tools/installkit.py`:137 (installers)
- **Repro:** Copy tools/ and florida/ to $S/ihtools/repo-copy, then:
  run its install_florida.py on a pristine copy
  rm repo-copy/florida/content/subjects/fl-wills/spotters.json; rm -rf repo-copy/florida/content/subjects/fl-ucc
  run install_florida.py again
The app still has content/subjects/fl-wills/spotters.json (the validator reports '2 spotters' from the stale file), content/subjects/fl-ucc is still there, and the catalog still lists fl-ucc, even though the docstring promises to '(or refresh)' the fl-* subjects. tools/lecturelib behaves the same way, keeping deleted or renamed modules.
- **Proposed fix:** For directory copies: after backing up dst, delete files in dst that are not in src (ignoring ._*, .DS_Store and __pycache__), or rmtree dst before copytree. In merge_catalog, drop entries with group == 'florida' whose id is not in `present`.
- **Verifier:** Confirmed in node against /home/user/Fire-Prep/app/js/lib/lectures-core.js. The STOP set (lines 5-13) includes "will" and "right". tokenize() drops both words, so search() hits `if (!qTerms.length) return [];` at line 73. With buildIndex over the passages "A will must be signed by the testator" and "the right to counsel attaches", search(i,'will') and search(i,'right') each return 0 results. The v

### [low] Catalog merge appends newly added pack subjects at the end instead of in pack order
- **File:** `tools/install_florida.py`:199 (installers)
- **Repro:** Use repo-copy2 with florida/content/subjects/fl-criminal moved out of the pack. install_florida.py on a pristine copy, put fl-criminal back, then install again (output: 'edited content/catalog.json').
Florida order in the catalog is now [... 'fl-ucc', 'fl-professional-responsibility', 'fl-criminal'], but catalog-florida.json puts fl-criminal between fl-evidence and fl-real-property.
The harness history shows this really happened: the 171654 backup has 11 subjects, after which fl-criminal was appended last. The order drives the Florida shelf and the planner's study order for fl-* ids, which aren't in ORDER.
- **Proposed fix:** After merging, put the pack subjects back in pack order. For example, remove every pack id from `subjects`, then insert the pack entries, in catalog-florida.json order, at the index of the first one that was removed (or append them when none existed).
- **Verifier:** I reproduced this, and the code shows it directly. exam_tips() in tools/lecturelib/pipeline.py:45-56 sorts tips by score, highest first. It does not keep them in text order. I ran it on a sample text where sentence 3 scores higher than sentence 1, and it returned [sentence 3, sentence 1]. withTips() in app/js/views/lectures.js:67-78 calls rest.indexOf(tip) and then sets rest to the text after that

## Not fully verified (fewer than 2 verdicts either way)

### [high] Sticky lecture player hides the focused control and the follow-along passage (and covers about 70% of the screen when the video fails)
- **File:** `app/css/lectures.css`:60 (ux-a11y)
- **Repro:** Harness on :4321, media served with `tools/lectures.py serve-media --root <dir> --port 4322` (a 170 s test mp4). Chromium at 1280x800. Script /tmp/claude-0/-home-user-Fire-Prep/e169ca09-de72-500f-ac94-fb779bdd7213/scratchpad/ux/t7.js uses page.route to serve a 40-passage version of florida-wills-01. It opens #/lectures/florida-wills-01-intestacy-and-elective-share-60eee4, focuses stamp #25 and presses Shift+Tab 20 times, then runs elementFromPoint at the centre of each focused element. Observed: 17 of 20 focused elements sit under .lec-player (sticky, 356 px tall). Follow-along (t9.js): play from passage 10, scroll up, let passage 11 become current. mark() centres it at top=262, but the player bottom is at 364, so the passage's first lines and its timestamp stay hidden. A second case (t8.js): when the current passage is at top=200, mark() does not scroll at all, because the code only checks `r.top < 120`. With the media server down (t6.js), the video errors and the error handler opens the 'Video not playing?' details inside the sticky box. The player then grows to 554 px of an 800 px viewport, and all 25 Shift+Tab stops land under it. Expected: focused controls and the current passage are visible below the player.
- **Proposed fix:** While the reader is mounted, keep the scroll area clear of the player. Use a ResizeObserver to set `document.documentElement.style.scrollPaddingTop = player.offsetHeight + 16 + 'px'` (only when getComputedStyle(player).position === 'sticky'), and clear it in destroy(). I applied this in t20.js and t9b.js: 0 of 20 focus stops were covered, and the follow-along passage landed at top=448, below the player. In mark(), replace `r.top < 120` with `r.top < player.getBoundingClientRect().bottom + 8`. Move mediaHelp (and the error note) out of `.lec-player`, or add `.lec-player.is-broken { position: static }` in the video 'error' handler.

### [high] Printing 'Where Florida differs' leaves out every Florida rule and authority (closed <details> stay closed in print)
- **File:** `app/css/florida.css`:31 (ux-a11y)
- **Repro:** t4.js: open #/florida/differences, call page.emulateMedia({media:'print'}), then page.pdf(). The print CSS hides `.fd-more summary` and sets `.fd-more{display:block}`, but the details element is still closed. checkVisibility() on the first `.fd-more p` returns false. `pdftotext fd.pdf - | grep -c 'For actions filed'` returns 0 (that is the first rule's text), and `grep -c 'Fla. Stat. § 48.193'` returns 0. The 40-page PDF has no rule text or authority, and the summary that would show anything is missing is hidden. Expected: the print shows each Florida rule and its authority, which is what the print CSS intends.
- **Proposed fix:** Open the disclosures for printing: return {el, destroy} from render() and add `const open = () => list.querySelectorAll('details.fd-more:not([open])').forEach(d => { d.dataset.printOpened = '1'; d.open = true; }); const close = () => list.querySelectorAll('[data-print-opened]').forEach(d => { d.open = false; delete d.dataset.printOpened; }); addEventListener('beforeprint', open); addEventListener('afterprint', close);` Remove both listeners in destroy(). With this simulated in t19.js, the PDF contains the rule text. On Chromium 131+, `.fd-more::details-content{content-visibility:visible}` inside @media print also works.

### [medium] Search-hit, On-tape and tip links round the start down with Math.floor, so the reader highlights and scrolls to the passage before the hit
- **File:** `app/js/views/lectures.js`:155 (views)
- **Repro:** I built an index in <scratchpad>/hunt-appjs/h2 (port 4393) from a Whisper JSON with fractional segment times. Chunk 1 starts at 82.96 and contains 'Celotex'. Script: hunt-appjs/js/floor.js. Open #/lectures?q=Celotex. The hit shows 1:23, but its href is ...?t=82. Clicking it gives: current passage = 0 (0:00 'Today we cover proposals...'), but 'Celotex' is in passage 1. seek() calls passageAt(chunks, 82.01), which returns the previous chunk, and the reader scrolls to that wrong passage. Real SRT, VTT and Whisper starts are fractional, so this happens on most hits. The same Math.floor pattern is at lectures.js:201 and 208 and at ui/lecture-links.js:30 and 34.
- **Proposed fix:** Don't truncate the time. Use `?t=${hit.start}` (likewise m.start and start in all five places); the starts are already rounded to 2 decimals. Number('82.96') then selects the right passage. You could also make seek() tolerant with `passageAt(chunks, t + 1)`.

### [medium] Going Back to the reader replays from the original ?t= and loses the student's progress
- **File:** `app/js/views/lectures.js`:332 (views)
- **Repro:** Script: hunt-appjs/js/back.js, same media setup as the first finding. Open #/lectures/<fl-wills-01>?t=5, click the 1:30 stamp, play to 92.4 s and pause. Click a topic pill in that passage, which goes to #/lectures?topic=..., then press Back. Observed: the hash is ...?t=5, video.currentTime=5.0, passage 0 is highlighted, and the saved position ends up as 5. Expected: resume at about 92. `startAt = query.t != null ? Number(query.t) : saved` always prefers the stale ?t in the URL. Every reader you reach from a search hit, an On-tape link or a tip link has ?t, so any detour plus Back rewinds the lecture.
- **Proposed fix:** Keep the URL in step with playback while the reader is showing. In the periodic save, and on 'pause', run `if (view.isConnected) { const qs = new URLSearchParams(location.hash.split('?')[1] || ''); qs.set('t', Math.floor(video.currentTime)); history.replaceState(null, '', `#/lectures/${encodeURIComponent(lec.id)}?${qs}`); }`. Then Back re-renders with the current time. The alternative is to prefer the saved position when the reader is reached by history traversal.

### [medium] Debounced library search rewrites the URL after you have navigated away, leaving a wrong hash and replacing the new page's history entry
- **File:** `app/js/views/lectures.js`:142 (views)
- **Repro:** Script: hunt-appjs/js/hash.js. On #/lectures, fill input.lec-search with 'homestead' and within 180 ms set location.hash='#/plan'. After 1.2 s: location.hash === '#/lectures?q=homestead' while the Plan (Calendar) view is displayed. Pressing Back then goes to '#/lectures', because the #/plan history entry was replaced. A reload or bookmark at this point opens the wrong page. The debounced runSearch keeps running after the view is replaced (the view has no destroy) and calls history.replaceState unconditionally.
- **Proposed fix:** Start the debounced function with `if (!input.isConnected) return;`. Alternatively return `{el, destroy}` from libraryView and cancel the pending debounce timer in destroy.

### [medium] 'Unsorted' subject chip uses the same '' key as 'All': wrong count, both chips pressed, and Unsorted can't be filtered
- **File:** `app/js/views/lectures.js`:103 (views)
- **Repro:** pipeline.process_lecture produces subject=null when neither the folder name nor the content matches a subject. I added a transcript 'Extras/pep talk.txt' and rebuilt h2 (port 4393). Script: hunt-appjs/js/unsorted.js, open #/lectures. Chips: 'All 9 pressed=true' ... 'Unsorted 9 pressed=true'. The count should be 1, and Unsorted should not be pressed. Clicking Unsorted leaves both pressed and still shows every shelf: Evidence, FL Civ Pro, ..., Unsorted. The search filter `filter ? p => p.subject === filter : null` also can't target unsorted passages, because their subject is null, not ''.
- **Proposed fix:** Use a sentinel for 'All', e.g. '*'. Write `let filter = query.subject || '*'`, use chips `[['*','All'], ...order.map(...)]` with `id !== '*' ? subjectDot(...) : null` and count `id !== '*' ? bySubject.get(id).length : index.lectures.length`. In paintShelves use `filter === '*' || id === filter`, and in search use `filter !== '*' ? p => (p.subject || '') === filter : null`.

### [medium] A query made only of stop words returns 'Nothing in the lectures for “will”' even when many passages discuss wills
- **File:** `app/js/lib/lectures-core.js`:73 (views)
- **Repro:** Script: hunt-appjs/js/stop.js on h2, which has three Florida Wills lectures. #/lectures?q=will shows 'Nothing in the lectures for “will”.' with 0 hits, while ?q=wills gives 3 passages. The same happens in node with hunt-appjs/js/core.mjs: search(buildIndex([{text:'A will must be signed ...'}]), 'will').length === 0, and the same for 'right' ('the right to counsel attaches'). STOP includes legally meaningful nouns (will, right, take, one...). tokenize() drops them, qTerms is empty, search returns [], and the UI says nothing matched.
- **Proposed fix:** In search(), fall back to a whole-word phrase scan when qTerms is empty: `if (!qTerms.length) { const ph = normalizePhrase(query); if (!ph.trim()) return []; return index.passages.filter(p => (!filter || filter(p)) && normalizePhrase(p.text).includes(ph)).slice(0, limit).map(p => ({ ...p, score: 1 })); }`. Use the same fallback in highlightRuns and snippet, so the word gets marked.

### [medium] A 'FLORIDA' badge sits in front of text that, in 161 of 185 entries, states the non-Florida rule
- **File:** `app/js/views/fl-differences.js`:60 (ux-a11y)
- **Repro:** Open #/florida/differences. The first item reads 'FLORIDA  UBE civil procedure tests federal subject-matter jurisdiction (diversity with more than $75,000…'. Others read 'FLORIDA  Federal Rule 4(m) allows 90 days…' and 'FLORIDA  Delaware and many MBE answers excuse demand when it would be futile…'. A script over content/subjects/fl-*/outline.json found that 161 of 185 `split` texts open with the UBE, MBCA, federal or majority rule, not the Florida one. Reading the badge as a label, a student learns the wrong rule (for example, that Florida allows 90 days for service).
- **Proposed fix:** Change the badge so it labels a comparison, for example `h('span.fd-label.smallcaps', 'vs. UBE')` or 'How Florida differs'. Do not label the sentence 'Florida'. The content files stay as they are.

### [medium] Lectures never link to Florida outline topics; Florida topic pills loop back to a lecture list
- **File:** `app/js/views/lectures.js`:53 (ux-a11y)
- **Repro:** Use the Florida track (fl-* subjects are in the catalog, and #/outlines/fl-wills/fl-wills.intestacy renders). Open #/lectures/florida-wills-01-intestacy-and-elective-share-60eee4 and click the 'Intestate succession' pill. It goes to #/lectures?topic=fl-wills.intestacy, which lists only the same lecture, with no 'Open the outline' button (screenshot moments-dark.png). A script confirmed that every fl-* topic id in the lecture index exists in the installed outlines. topicHref() (line 53) and momentsView (line 210) both exclude `fl-` subjects, even though nameBook() already marks them `library:true` from the catalog.
- **Proposed fix:** Drop the `fl-` special case and rely on catalog membership. In topicHref use `return s.library ? '#/outlines/…' : '#/lectures?topic=…'`. In momentsView use `!isRule && names.subject(t.subject).library ? h('p', h('a.btn.ghost.sm', { href: `#/outlines/${encodeURIComponent(t.subject)}/${encodeURIComponent(id)}` }, …)) : null`. fl-contracts, which has no outline, is not in the catalog, so it keeps the moments page.

### [medium] 'All 6 lectures →' in the On tape box opens a page that says '1 lecture discuss this.'
- **File:** `app/js/ui/lecture-links.js`:35 (ux-a11y)
- **Repro:** t15.js routes links.json so that 5 rules of fl-wills.intestacy each have a different lecture, while the topic itself still has 1. On #/outlines/fl-wills/fl-wills.intestacy the On tape box lists 4 lectures and 'All 6 lectures →'. Clicking it opens #/lectures?topic=fl-wills.intestacy, which shows only '1 lecture discuss this.' and one row. The box combines topic and rule moments, but momentsView (lectures.js:185) reads only links.topics[id]. The lede also has a grammar error for one lecture ('1 lecture discuss this.'), which also shows with the unmodified harness data.
- **Proposed fix:** In momentsView, for a topic, also include rule moments, removing duplicate lectures: `const ids = [id, ...Object.keys(links?.rules || {}).filter(k => k.startsWith(id + '.'))]; const seen = new Set(); const moments = ids.flatMap(k => momentsFor(links, k)).filter(m => !seen.has(m.lecture) && seen.add(m.lecture)).sort((a, b) => b.score - a.score);`. For the lede, use `rows.length === 1 ? '1 lecture discusses this.' : `${rows.length} lectures discuss this.``, counting only rows that have meta.

### [medium] Filters are lost on Back: the differences search and subject, and the lecture-library subject chip
- **File:** `app/js/views/fl-differences.js`:64 (ux-a11y)
- **Repro:** t12.js: on #/florida/differences, click 'FL Property', type 'homestead' (2 differences), click the first rule, then go back. The URL is #/florida/differences, the list shows '185 differences', the input is empty and 'All' is pressed. On #/lectures, click 'FL Wills' and type 'homestead' ('1 passage for “homestead”'), open the hit, then go back. The URL is #/lectures?q=homestead, the chip is reset to 'All', and the results change to '3 passages for “homestead”'. Because the router re-renders on every hash change, any state that is not in the URL is lost.
- **Proposed fix:** In fl-differences paint(), add `history.replaceState(null, '', '#/florida/differences' + qs({subject, q: input.value.trim()}))` and set the input's initial value from `query.q`. In lectures.js runSearch (line 142) and the chip onclick, write `subject` as well: `'#/lectures' + qs({ q, subject: filter })`, using URLSearchParams and leaving out empty values. Use replaceState, which fires no hashchange, so nothing re-renders.

### [medium] Low-contrast text: secondary topic pills (opacity .7) and the 'What the lecturers flag' heading
- **File:** `app/css/lectures.css`:94 (ux-a11y)
- **Repro:** t3.js computes WCAG contrast against the composited background, including opacity. `.lec-topic.minor` (11px uppercase, for example 'Elective share…' on #/lectures/florida-wills-01-…) measures 2.43:1 in light and 3.17:1 in dark (data-theme=dark), below 4.5:1. The opacity:.7 rule causes this: the same pill without it measures 3.92:1 and 5.21:1. `.lec-tipbox h2` (11px brass smallcaps, on #/lectures?topic=fl-wills.intestacy) measures 3.52:1 in light.
- **Proposed fix:** Remove `opacity:.7` and mark minor pills with the border instead, for example `.lec-topic.minor { border-style: dashed; }` or `border-color: var(--hair-strong)` with the text at `var(--ink-3)`. For the heading use `.lec-tipbox h2 { color: var(--ink-2) }` and keep the brass colour only on the star icon (`.lec-tipbox h2 svg { color: var(--brass) }`).

### [medium] Media server lets any website read any file under --root: 'Access-Control-Allow-Origin: *', dotfiles served, Host header never checked (DNS rebinding)
- **File:** `tools/lecturelib/mediaserver.py`:33 (security-perf)
- **Repro:** Work dir: /tmp/claude-0/-home-user-Fire-Prep/e169ca09-de72-500f-ac94-fb779bdd7213/scratchpad/secperf. (1) mkdir media/root; printf 'Bud1 Evidence/hearsay.srt Wills/intestacy.mp4' > media/root/.DS_Store; python3 /home/user/Fire-Prep/tools/lectures.py serve-media --root media/root --port 47821 &; curl -si -H 'Origin: https://evil.example' -H 'Host: rebound.evil.example:47821' http://127.0.0.1:47821/.DS_Store  -> 'HTTP/1.0 200 OK', 'Access-Control-Allow-Origin: *', body returned. The forged Host is accepted, so DNS rebinding also works. (2) Browser proof (cors.js + run_media.py in the work dir): a page served from a different origin (http://localhost:47813) runs fetch('http://127.0.0.1:47811/.env'). Against the add-on as shipped this gives '200 "HIDDEN\n"' and also reads sub/a.vtt. Against the same handler without the ACAO header the fetch fails ('Failed to fetch'). In both cases <video src=http://127.0.0.1:PORT/lecture.webm> loads and seeks ('seeked to 15 duration 20'), so the CORS header is not needed for playback. On macOS every folder viewed in Finder has a .DS_Store that lists its filenames, so a hostile page can list folders and fetch every transcript or video even though directory listing returns 404. Expected: only the app's <video> element can load media; other origins and other Host values get nothing; dotfiles are never served.
- **Proposed fix:** In RangeHandler: (a) remove send_header('Access-Control-Allow-Origin', '*'). A <video> without a crossorigin attribute does not use CORS. If CORS is ever needed, echo only http://127.0.0.1:4321 and http://localhost:4321. (b) In _serve, before resolving, reject a bad Host: `host = (self.headers.get('Host') or '').rsplit(':', 1)[0].lower(); if host not in {'127.0.0.1', 'localhost', '[::1]', configured_host}: return self.send_error(403)`. (c) In _resolve, return None when any(part.startswith('.') for part in Path(rel).parts). Optionally also return None unless target.suffix.lower() is in formats.MEDIA_EXTS + ('.vtt',).

### [medium] Full index build takes 34-42 s on a realistic 100 h corpus; most of it ranks all ~1,400 rules for every passage and then throws away rules outside the 3 tagged topics
- **File:** `tools/lecturelib/pipeline.py`:200 (security-perf)
- **Repro:** Run python3 /tmp/claude-0/-home-user-Fire-Prep/e169ca09-de72-500f-ac94-fb779bdd7213/scratchpad/secperf/gen.py <harness> corpus. It makes 80 SRT lectures, 100.0 h, 1,035,130 words, plus a library of 1,428 rules / 288 topic targets built from the harness outlines. Then: time python3 tools/lectures.py build --transcripts corpus/transcripts --library corpus/lib --out o1 -> 34.4 s and 41.9 s wall (4,347 passages). cProfile: Tagger.tag 60 of 69 s; TfIdf.rank 45.5 s over 8,526 calls (50.9M dict.get); about two thirds of rank time is the rule model (3.79 s rule vs 1.88 s topic for 20 lectures). Each call scores every rule, does a full sorted() over all candidates, keeps the global top 25, then keeps only rules whose topic is in the 1-3 tagged topics. The signature covers every library topic's text, so any edit to library content causes this full re-tag again, including under --watch. For comparison: incremental no-change rebuild 1.5 s, CLI search 2.2-2.5 s, browser first search including indexing 1.15 s (one 412 ms long task). Those are fine.
- **Proposed fix:** In Tagger.__init__, precompute `self.rules_of_topic = {tid: [rule_idx, ...]}`. In tag(), replace the global self.rule_model.rank(t_terms, top=25) with: `q = self.rule_model.vector(t_terms)`; for each distinct tagged topic, `for ridx in self.rules_of_topic[tid]: s = TfIdf.cosine(q, self.rule_model.vectors[ridx])`; keep s >= MIN_RULE_SCORE; sort; take 3. In TfIdf.rank use heapq.nlargest(top, ...) instead of sorting everything. Verified with fastbuild3.py: identical tags and rules on all 4,347 passages, 41.9 s -> 24.4 s. This also removes the global top-25 cut that could hide in-topic rules. To get under 10 s, also run process_lecture in a ProcessPoolExecutor with an initializer that builds the Tagger once per worker: 7.8 s with 4 processes (parbuild.py).

### [low] withTips() assumes tips are in text order, but exam_tips() returns them strongest first, so the earlier tip is never highlighted
- **File:** `app/js/views/lectures.js`:67 (views)
- **Repro:** I added 'Real Property/02 Homestead tips.txt' and rebuilt h2. Its chunk has tips = ['The bar examiners love to test ... trap on the exam.' (sentence 3), 'Remember that homestead protection ...' (sentence 1)]. Script: hunt-appjs/js/tips.js, open #/lectures/real-property-02-homestead-tips-219f42. Observed: only one mark.lec-tip ('The bar examiners love to test...'). The first sentence is not marked, because withTips() consumes `rest` past the first tip it finds, so a tip earlier in the text is never found.
- **Proposed fix:** Place each tip by its index in the full text: `const spans = tips.map(t => [text.indexOf(t), t]).filter(([i]) => i >= 0).sort((a, b) => a[0] - b[0]); let at = 0; for (const [i, tip] of spans) { if (i < at) continue; out.push(text.slice(at, i), h('mark.lec-tip', {title: 'Flagged by the lecturer'}, tip)); at = i + tip.length; } out.push(text.slice(at));`

### [low] The 'All N lectures →' link counts rule matches, but the page it opens lists only topic-tagged moments
- **File:** `app/js/ui/lecture-links.js`:35 (views)
- **Repro:** In h2's links.json, topic fl-evidence.hearsay has 1 lecture, and rules under fl-evidence.hearsay.* point to 5 other lectures; I added these to show the case. Script: hunt-appjs/js/aside.js. Open #/outlines/fl-evidence/fl-evidence.hearsay: the aside shows 4 rows and 'All 6 lectures → #/lectures?topic=fl-evidence.hearsay'. Clicking it shows the lede '1 lecture discuss this', with 1 row. lectureAside merges momentsFor(topic) with momentsFor(each rule), but momentsView only calls momentsFor(links, id). This is common for library topics, where lectures are mostly linked through rule matches.
- **Proposed fix:** In momentsView, when !isRule, merge the rule moments under the topic, keeping the best moment per lecture: `const all = [...momentsFor(links, id), ...Object.keys(links?.rules || {}).filter(k => k.startsWith(id + '.')).flatMap(k => momentsFor(links, k))]; const best = new Map(); for (const m of all) if (!best.has(m.lecture) || m.score > best.get(m.lecture).score) best.set(m.lecture, m); const moments = [...best.values()].sort((a, b) => b.score - a.score);`. The other option is to have the aside count only topic moments for the link.

### [low] snippet() finds the hit by a raw substring of the stem, so the shown excerpt often contains no highlighted word
- **File:** `app/js/lib/lectures-core.js`:125 (views)
- **Repro:** Script: hunt-appjs/js/snip.js on h2: #/lectures?q=wills. The top hit '03 Wills Review' snippet is 'You will see this again and again, ...' and has 0 <mark> elements, because the stem 'will' matched the stop word 'will' at index 4 and 'holographic wills' falls outside the 260-character window. In node (hunt-appjs/js/core.mjs), highlightRuns(snippet(text,'wills'),'wills') has no hits. Likewise snippet('The client signed... <300 chars>... A charging lien ...', 'lien') starts at 'client', because 'lien' is a substring of 'client', and has no hit.
- **Proposed fix:** Find the first word whose token is a query stem, as highlightRuns does: `const stems = new Set(tokenize(query)); const re = /[A-Za-z0-9’']+/g; let m, pos = -1; while ((m = re.exec(text))) { if (tokenize(m[0]).some(t => stems.has(t))) { pos = m.index; break; } }`.

### [low] Filter text and subject chip are lost when you come Back from a rule (and the Lectures library also loses its subject chip)
- **File:** `app/js/views/fl-differences.js`:32 (views)
- **Repro:** Script: hunt-appjs/js/fd.js. On #/florida/differences, click 'FL Evidence' and type 'hearsay', which gives 8 differences. Click the first rule link: the outline opens and flashes the rule. Press Back. Observed: hash '#/florida/differences', q '', '185 differences', 'All' pressed, so the filter is gone. The page's purpose is to open each rule and return. The same happens in the Lectures library (stop.js): choose the 'FL Wills' chip, search 'homestead', open a hit, press Back. The URL is '#/lectures?q=homestead' with 'All' pressed and hits from every subject, because runSearch's replaceState drops `subject`. The router re-renders on every hash change, and neither view writes its state to the URL.
- **Proposed fix:** In fl-differences, set `input.value = query.q || ''`. At the end of paint(), add `if (input.isConnected) history.replaceState(null, '', '#/florida/differences' + (() => { const p = new URLSearchParams(); if (subject) p.set('subject', subject); if (input.value.trim()) p.set('q', input.value.trim()); const s = p.toString(); return s ? '?' + s : ''; })());`. In lectures.js:142, also write `subject` (when filter is set) into the replaceState URL.

### [low] Screen-reader search status: the lecture results announce the whole list, and the differences count announces nothing
- **File:** `app/js/views/lectures.js`:110 (ux-a11y)
- **Repro:** t16.js: on #/lectures, type 'spouse'. The only live region is `section.lec-results[aria-live=polite]`, which holds the heading plus every hit (5 links and 1,317 characters here, up to 40 hits with real data). Each debounced keystroke, and each 'Indexing lectures… n / total' update, re-announces that whole region. On #/florida/differences, typing 'homestead' changes the count to '6 differences', but the page has 0 aria-live or role=status elements, so the change is never announced, including when it reaches 'Nothing matches.'.
- **Proposed fix:** In lectures.js, remove aria-live from the section and add a small status element, `const status = h('p.visually-hidden', { role: 'status' })`. Set its text to the hit-count sentence, or to 'Indexing…' only once, not on every progress tick. In fl-differences.js give the count `role: 'status'` (`h('span.muted.num', { role: 'status' })`).

### [low] Deep links (?t=) scroll to the passage, but the first Tab jumps back to the top of the page
- **File:** `app/js/views/lectures.js`:336 (ux-a11y)
- **Repro:** t18.js (40-passage lecture): open #/lectures/florida-wills-01-intestacy-and-elective-share-60eee4?t=3000. The page scrolls to scrollY=9536 and focus is on #view. A single Tab moves focus to the 'Lectures' back link and scrolls to y=0. Reaching the deep-linked passage's 'Play from 50:00' button took 117 Tab presses. Every search hit, On tape link and tip link uses this deep-link form.
- **Proposed fix:** After scrolling to the target, move focus to it: `const b = items[current].querySelector('.lec-stamp'); b.focus({ preventScroll: true });`. If the stamp is disabled, give the li `tabindex=-1` and focus the li instead.

### [low] 'All Florida Part A' in #/mbe: the set is named with 12 subjects, 'null' shows in the summary, and keyboard focus is lost
- **File:** `tools/install_florida.py`:180 (ux-a11y)
- **Repro:** t10.js: on #/mbe, focus the 'All Florida Part A' chip and press Enter. document.activeElement becomes BODY, because paint() runs chips.replaceChildren() and removes the focused chip; the next Tab goes to 'Skip to content'. The summary text reads '17 questions with feedback after each answer.null'. The cause is the existing `summary.replaceChildren(..., n < count && n ? … : null)`, which this pool always triggers. Clicking 'Call the first question' stores the label 'FL Civ Pro, FL Con Law, FL Business, FL Wills, FL Trusts, FL Family, FL Evidence, FL Criminal, FL Property, FL Torts, FL UCC, FL Ethics', which also shows on the Resume banner and in Past sets.
- **Proposed fix:** Add one more replacement to the mbe.js Replace patch in install_florida.py. In the label expression, check flIds before the subject join: `… ? 'Mixed MBE' : flIds.length && chosen.size === flIds.length && flIds.every(id => chosen.has(id)) ? 'Florida Part A' : subs.filter(…)…`. Change the summary's trailing `: null` to `: ''`. In paint(), remember the focused chip's index before replaceChildren and focus that index afterwards, or update aria-pressed in place instead of rebuilding the chips.

### [low] Malformed request (NUL in path, or Range number over 4,300 digits) raises an uncaught ValueError: no HTTP response, traceback on the console
- **File:** `tools/lecturelib/mediaserver.py`:43 (security-perf)
- **Repro:** Run python3 /tmp/claude-0/-home-user-Fire-Prep/e169ca09-de72-500f-ac94-fb779bdd7213/scratchpad/secperf/ms_probe.py <root>, or send raw requests to `lectures.py serve-media`: 'GET /v.mp4%00.txt HTTP/1.0' -> connection closes with 0 bytes, and the server prints 'ValueError: lstat: embedded null character in path' from Path.resolve() in _resolve. 'GET /v.mp4' with 'Range: bytes=' + '9'*5000 + '-' -> 0 bytes, and the server prints 'ValueError: Exceeds the limit (4300 digits) for integer string conversion' from int(m.group(1)) on Python 3.11+. Expected: 404 for the first and 416 (or the Range ignored) for the second, with no traceback.
- **Proposed fix:** In _resolve, wrap the unquote/resolve/relative_to/is_file block in `try: ... except (ValueError, OSError): return None`. Limit range numbers in the regex, e.g. `_RANGE = re.compile(r'bytes=(\d{0,18})-(\d{0,18})$')`, or wrap the int() conversions in try/except ValueError and send 416.

### [low] Range parsing answers 416 to Range headers it should ignore (unknown unit, uppercase 'Bytes', multi-range, whitespace)
- **File:** `tools/lecturelib/mediaserver.py`:66 (security-perf)
- **Repro:** Against the add-on server (ms_probe.py): 'Range: items=0-9' -> 416, 'Range: Bytes=0-9' -> 416, 'Range: bytes=0-1,5-6' -> 416, each with 'Content-Range: bytes */1000'. RFC 9110 section 14.2 says a server MUST ignore a Range with a unit it does not understand, and range unit names are case-insensitive. A server that does not support multipart ranges may ignore the header and send 200. Clients sending these forms get no content at all instead of the full file. Valid single ranges work: 'bytes=0-9' -> 206 'bytes 0-9/1000', 'bytes=-10' -> 206 'bytes 990-999/1000', 'bytes=5000-' -> 416 (correct).
- **Proposed fix:** Parse case-insensitively and allow whitespace: `_RANGE = re.compile(r'\s*bytes\s*=\s*(\d*)\s*-\s*(\d*)\s*$', re.I)`. When the header does not match (other unit, a comma-separated list, garbage), ignore it and serve 200 with the whole file. Send 416 only for a well-formed single range that cannot be satisfied (start >= size, last < first, or 'bytes=-0').

