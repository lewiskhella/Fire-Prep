# Fire Prep — companion tools for the Ruled bar-prep app

The Ruled app (website, study app and content library) lives on the Mac in
`/Volumes/Extreme Pro/Bar Prep App`. This repository holds add-ons built for it
in the cloud, packaged so one command installs them into that folder.

**First add-on: Lectures (§ 11).** It turns the transcripts of your Florida Bar
lecture videos into a searchable library inside the app:

- Every lecture is cut into ~75-second passages. Each passage is tagged with the
  subject and topic it teaches: Florida Part A topics (homestead, proposals for
  settlement, the Florida Evidence Code, the elective share…) and the app's own
  UBE outline topics and rules.
- Search every transcript at once. Open a lecture to read it passage by passage,
  press a timestamp to play the video from there, and follow along as it plays.
- Every outline topic in the app gets an **On tape** box linking to the lecture
  moments that teach it.
- Reports show lecture time per topic against what the library already covers,
  and authoring briefs list what to write next for the Florida subjects.

## Install on the Mac

```bash
# 1. Get this repo onto the Mac (or download the ZIP from GitHub)
git clone https://github.com/lewiskhella/Fire-Prep.git ~/Fire-Prep

# 2. Add the Lectures section and tools to the app (backs up every file it touches)
python3 ~/Fire-Prep/tools/install_lectures.py "/Volumes/Extreme Pro/Bar Prep App"

# 3. Index the transcripts (run from the app folder; re-run as more finish transcribing)
cd "/Volumes/Extreme Pro/Bar Prep App"
python3 tools/lectures.py build \
    --transcripts "/path/to/Florida Bar transcripts" \
    --library .
#   add --media-root "/path/to/the videos" if the videos aren't next to the transcripts
#   add --watch 600 to keep refreshing every 10 minutes while transcription runs

# 4. (Optional) serve the videos so "play from here" works
python3 tools/lectures.py serve-media --root "/path/to/the videos"

# 5. Open the app
open http://localhost:4321/app/#/lectures
```

Undo the install with `python3 ~/Fire-Prep/tools/install_lectures.py "/Volumes/Extreme Pro/Bar Prep App" --uninstall`.

Only the Python 3 standard library is needed (the Mac's stock `python3` works). No npm, no build step.

## Commands

| Command | What it does |
|---|---|
| `lectures.py build --transcripts DIR` | Parse, tag and index every transcript under DIR (incremental). |
| `lectures.py search "elective share"` | Search across all lectures, with timestamps. |
| `lectures.py coverage --library .` | Markdown report: lecture minutes per topic vs. rules/questions/essays in the library; flags gaps and phrases the lectures repeat that the library never mentions. |
| `lectures.py brief fl-wills` | Authoring brief for one subject: what to cover, recurring terms, and where to re-listen. |
| `lectures.py corpus --dest DIR` | Plain-text export for the originality checker's reference corpus. |
| `lectures.py serve-media --root DIR` | Local video server with seeking (byte ranges) on port 4322. |

Transcript formats: `.srt`, `.vtt` (including YouTube-style rolling captions, de-duplicated),
Whisper / mlx-whisper / faster-whisper `.json`, whisper.cpp `-oj` `.json`, Whisper `.tsv`,
and `.txt`/`.md` (with `[hh:mm:ss]` stamps, or plain text with estimated timing).
When one lecture has several formats, the richest is used.

## Where the index lives

`lectures.py build` writes to `content/lectures/` in the app folder by default (`--out` changes it):
`index.json`, one file per lecture in `lectures/`, and `links.json`. Re-running it only
re-processes transcripts that changed.

## Florida

`tools/lecturelib/taxonomies/florida.json` lists the Florida Part A subjects and topics
used for tagging, with ids such as `fl-wills.spousal-and-family-protection`. It is a
keyword list for tagging, not legal content. Check the subject list against the Florida
Board of Bar Examiners' current study guide. [`docs/FLORIDA-TRACK.md`](docs/FLORIDA-TRACK.md)
proposes how to add a Florida exam track to the app, using these same ids.

## Repository layout

```
app/js/views/lectures.js     § 11 Lectures view (library, search, reader, topic moments)
app/js/lib/lectures.js       loads content/lectures/*; per-device prefs (ruled:lectures:v1)
app/js/lib/lectures-core.js  pure search/format helpers (shared, unit-tested)
app/js/ui/lecture-links.js   "On tape" box for outline topics
app/css/lectures.css         styles on the app's shared tokens
tools/lectures.py            command-line tool
tools/lecturelib/            parsers, tagger, index builder, media server, Florida taxonomy
tools/install_lectures.py    installs the above into the app folder
tests/                       python3 -m unittest discover -s tests
                             node --test tests/lectures-core.test.mjs
docs/                        INTEGRATION.md (data contract, manual install), FLORIDA-TRACK.md
```
