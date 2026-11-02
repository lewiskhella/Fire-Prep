# Integrating Lectures into Ruled

This is for whoever maintains the app (you, or the Claude session working in
`/Volumes/Extreme Pro/Bar Prep App`). `tools/install_lectures.py` does all of this
automatically. Do it by hand only if the installer reports `SKIPPED` because an
anchor line changed.

## Files added

| Path in the app | Purpose |
|---|---|
| `app/js/views/lectures.js` | View for `#/lectures`, `#/lectures?q=…`, `#/lectures?topic=<id>` / `?rule=<id>`, `#/lectures/<lectureId>?t=<sec>` |
| `app/js/lib/lectures.js` | Fetches `content/lectures/{index,links}.json` and `lectures/<id>.json`; prefs in `localStorage['ruled:lectures:v1']` (media server URL, playback rate, last position per lecture) |
| `app/js/lib/lectures-core.js` | Pure helpers: tokenise/stem (mirrors the Python side), passage search, highlighting, clock formatting |
| `app/js/ui/lecture-links.js` | `lectureAside(topic)` returns the "On tape" box; it stays hidden when there is no index or no match |
| `app/css/lectures.css` | Styles; uses only `shared/tokens.css` variables, so Paper and Chambers both work |
| `tools/lectures.py`, `tools/lecturelib/` | Command-line tool and library |

The main store (`ruled:v1`) is untouched. Lecture preferences use their own key, so
the store schema and its export/import stay as they are.

## Edits to existing files

1. `app/js/main.js`: before `route('*', …)`:
   ```js
   route('/lectures', () => import('./views/lectures.js'));
   route('/lectures/:id', () => import('./views/lectures.js'));
   ```
2. `app/js/ui/shell.js`: in `NAV`, after the Bench Book entry:
   ```js
   { sec: '11', path: '/lectures', label: 'Lectures', icon: 'play' },
   ```
3. `app/index.html`: after the `css/views.css` link:
   ```html
   <link rel="stylesheet" href="css/lectures.css">
   ```
4. `app/js/views/topic.js`:
   - Add `import { lectureAside } from '../ui/lecture-links.js';`.
   - Put `lectureAside(t),` in the page just before `rules.length ? list : emptyState(…)`.

The service worker needs no change. It is network-first and caches what's fetched,
so the lecture JSON is cached the first time it is opened.
`content/lectures/` is not read by `validate_content.py` (it only reads catalog subjects, the guide and the MPT files). Nothing needs adding to `SHELL`.

## Data contract (`content/lectures/`)

`index.json`
```jsonc
{
  "schema": 1, "generated": "2026-11-02T14:59:00",
  "taxonomySignature": "…",            // rebuilds re-tag everything when this changes
  "totals": { "lectures": 7, "seconds": 547.2, "words": 970 },
  "subjects": [ { "id": "fl-wills", "title": "Wills & Administration of Estates", "source": "builtin",
                  "part": "A", "rulesSubject": "wills", "lectures": 2,
                  "topics": [ { "id": "fl-wills.intestacy", "title": "Intestate succession" } ] },
                { "id": "evidence", "source": "library", "rulesSubject": "evidence", … } ],
  "lectures": [ { "id": "florida-wills-01-intestacy-and-elective-share-60eee4",
                  "title": "01 Intestacy and Elective Share", "folder": "Florida Wills",
                  "subject": "fl-wills", "subjectSource": "name|content",
                  "duration": 160.0, "timing": "exact|estimated", "words": 412,
                  "source": { "path": "Florida Wills/01 Intestacy and Elective Share.srt", "format": "srt", "sha1": "…" },
                  "media": { "root": "media|transcripts", "path": "Florida Wills/01 Intestacy and Elective Share.mp4" },
                  "topTopics": [ { "topic": "fl-wills.intestacy", "seconds": 90.0 } ],
                  "chunks": 2 } ],
  "errors": [ { "path": "broken.json", "error": "invalid JSON: …" } ]
}
```

`lectures/<id>.json` is the same lecture record, with `chunks` as a list:
```jsonc
{ "i": 0, "start": 0.0, "end": 90.0, "text": "…",
  "tags":  [ { "subject": "fl-wills", "topic": "fl-wills.intestacy", "score": 0.936 } ],   // best first, up to 3
  "rules": [ { "rule": "wills.intestacy.shares", "topic": "wills.intestacy", "score": 0.41 } ] }  // library rules only
```

`links.json` lists the best moments for each topic or rule, one per lecture, strongest first:
```jsonc
{ "fields": ["lecture", "chunk", "start", "score"],
  "topics": { "fl-wills.intestacy": [["florida-wills-01-…", 0, 0.0, 0.936]] },
  "rules":  { "evidence.hearsay-803.excited-utterance": [["evidence-hearsay-part1-…", 0, 0.0, 0.464]] } }
```

Lecture ids come from the transcript's path relative to `--transcripts`. They stay
stable across rebuilds, so saved positions and deep links keep working. Renaming a
file gives the lecture a new id.

## How tagging works

- Every topic is a document: the Florida taxonomy's title and keywords, or the
  library outline's title, intro and the full text of every rule.
- Each passage is scored by TF-IDF cosine similarity (unigrams and bigrams, light
  stemming), plus a bonus for exact keyword phrases such as "proposal for settlement" or "768.79".
- Topics scoring at least 0.12 are kept (up to 3).
- Library rules inside those topics scoring at least 0.16 are linked (up to 3).
- **Lecture subject:** the folder or file name decides when it names a subject.
  When a name could mean either the Florida subject or its UBE twin (for example
  "Evidence"), the lecture's own tagged content decides between them.
- Thresholds are constants at the top of `tools/lecturelib/pipeline.py`. Bump
  `PIPELINE_VERSION` when tagging logic changes, so cached lectures are reprocessed.

## Verifying

- `python3 -m unittest discover -s tests`: parsers, tagging, incremental rebuilds,
  media byte ranges, the installer (install, idempotency, missing anchors, uninstall).
- `node --test tests/lectures-core.test.mjs`: search and formatting helpers.
- The view was also run end to end in Chromium, against a copy of the app rebuilt from
  its source. Checked: the library, search, the reader with video seek and follow-along,
  topic moments and the On-tape box, plus phone width (390 px) and Chambers dark mode.
