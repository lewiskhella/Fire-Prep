# The Florida exam track

> **Status: built.** Steps 1–3 below are implemented by `tools/install_florida.py` and the
> content in `florida/`. The jurisdiction switch is `profile.jurisdiction`: "Florida" means
> MBE + Florida Part A, any other value means the UBE, and blank shows everything. Step 4,
> the authoring loop, is how to grow and correct the pack from the lectures. The original
> proposal follows.


Ruled is built for the UBE: MBE, MEE and MPT across 14 subjects. Florida is not a UBE
jurisdiction. Its General Bar Examination pairs a Florida-specific **Part A** with
**Part B**, the MBE. There is no MEE or MPT. Your Florida Bar lectures cover the
Florida material, so this is how the app could grow a Florida track. It is a proposal:
nothing in this repo changes the app's catalog or content.

> **Confirm before building.** Check the exam's format, timing, subject list and any
> move to NCBE's NextGen exam against the Florida Board of Bar Examiners' current
> materials. The outline below is from memory and is not authoritative.

## What changes for a Florida candidate

| | UBE (today) | Florida |
|---|---|---|
| Day 1 | MEE (6 essays) + MPT (2 tasks) | Part A: Florida essays (morning) + Florida multiple choice (afternoon) |
| Day 2 | MBE | Part B: MBE (unchanged; all MBE subjects, drills and outlines apply as-is) |
| Subjects | 8 MBE + 6 MEE-only | 8 MBE + the Florida Part A list (see `tools/lecturelib/taxonomies/florida.json`) |

So everything built for the MBE carries over. The Florida work is Part A: Florida
outlines, Florida-style multiple choice, and Florida essays.

## Build plan

1. **Subjects.** Add `fl-*` subjects to `content/catalog.json` with `group: "florida"`:
   - Use the same ids as the lecture taxonomy (`fl-civil-procedure`, `fl-constitutional-law`,
     `fl-wills`, `fl-trusts`, `fl-family-law`, `fl-evidence`, `fl-criminal`,
     `fl-real-property`, `fl-torts`, `fl-business-entities`, `fl-ucc`,
     `fl-professional-responsibility`, …).
   - Topic ids then match the lecture tags exactly, so the On-tape links appear with
     no further wiring.
   - Content uses the existing schema unchanged: `outline.json`, `questions.json`
     (4 choices) and `essays.json` (the validator already allows `minutes` up to 120).
2. **Jurisdiction switch.** `profile.jurisdiction` exists but nothing reads it yet.
   - Turn it into a choice between UBE and Florida.
   - Filter catalog subjects by group.
   - For Florida, hide MEE and MPT. Rename "MEE Essays" to "Part A Essays" and use the
     Part A essay length on the clock.
   - Give the planner (`planner.js` `BASE_WEIGHT`) weights for the `fl-*` ids.
     Unknown ids currently default to 0.8.
3. **Exam profile.** Add a Florida `exam` block (components and pacing) next to the
   UBE one in `catalog.json`. Check `time.js` `upcomingAdministrations()` against
   Florida's exam dates.
4. **Authoring loop.** This reuses the batch, review and originality workflow the
   library was built with:
   ```bash
   python3 tools/lectures.py coverage --library . > docs/LECTURE-COVERAGE.md   # what's lectured most, what's missing
   python3 tools/lectures.py brief fl-wills > .staging/fl-wills-brief.md        # topics, terms, where to re-listen
   python3 tools/lectures.py corpus --dest tools/.lecture-corpus                 # so originality.py can check against the lectures
   ```
   - Authors write original rules from primary sources: Florida Statutes, the Florida
     Rules of Civil and Criminal Procedure, the Rules Regulating The Florida Bar, and
     Florida Supreme Court decisions.
   - Each rule cites its `authority`.
   - Run the originality check against both the study files and the lecture corpus.
   - Florida law has changed a lot recently (tort reform, alimony, summary judgment
     standards), so every Florida batch needs an accuracy reviewer who checks dates of
     amendment, and an attorney pass before sale.
5. **Order of work.** Start with the subjects the lectures spend the most time on
   (from the coverage report) and that have no UBE twin. Florida constitutional law,
   professional responsibility and Florida civil procedure have none. Wills, trusts and
   family law have UBE twins whose rules differ in Florida-specific ways.
