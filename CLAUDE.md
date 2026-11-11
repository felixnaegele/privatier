# Privatier: working notes

Local tool that anonymises research folders before they go to a cloud AI. The owner is a clinician-scientist, not a
software engineer: explain in plain words, recommend rather than list options, and say when something is finished.

## Rules decided by the owner
- **Never assume, never make things up.** What the data does not settle stays apart and becomes a question. Flagging is
  fine, but ask as little as possible.
- **Tables first** (Excel, SPSS, CSV): as straightforward as possible, minimal input. Letters are secondary, and more
  flags are acceptable there.
- **German and English** get equal attention.
- **People:** one person gets one code, and people with the same name are never merged. Birth date or ID tells them apart.
- **No information lost (level 1):** every cell in a non-identifying column comes out exactly as it went in.
- **Dates other than birth dates (level 1)** (surgery, follow-up, death) keep day and month. Birth dates become the
  year, with the full date kept in the encrypted key.
- **Privacy levels:** 1 pseudonymised (default), 2 less detail, 3 strongly reduced, 4 anonymisation attempt. At level 2
  **age stays exact**: important for clinical data. Levels 3 and 4 keep no key. See `README.md`.
- **The word "anonymous"** is used only at level 4, and only if the check on the files as written supports it. "Could
  not check" never counts as safe. No output folder may be called anonymous by default.
- **File and folder names are never changed**, so users can keep track of their files.
- **Do not test for the sake of testing.** Tell the owner when the necessary tests are done, and move on.

## Practical notes
- Never print cell values from `real_testdata/` (gitignored): only headers, counts and shapes. Test on copies filled with
  mock data, except for tools that only print verdicts.
- This session type cannot write to `.git`: give the owner the commit and push commands to run in Terminal, naming the
  paths (`git add README.md CLAUDE.md src tests tools`), never `git add .`.
- The window library cannot be installed from a sandboxed session: test `app/service.py` and `ui.html` here, and let the
  owner open the real window.
- Use `.venv/bin/python -m pytest` and `.venv/bin/python -m pip`.
- The app and the dmg are built with `sh packaging/build_app.sh`. A sandboxed session can build the app and run its
  self-test (`dist/Privatier.app/Contents/MacOS/Privatier --self-test`), but not the dmg: the owner runs
  `sh packaging/build_app.sh --dmg-only` in Terminal.
- `tools/ui_demo.py <folder>` writes the screen with made-up data, to look at it in a browser.
- Findings and their ids hold real values: they go to the screen only, never into a file, log or report.

## Checks to run after changing the engine
- `pytest`
- `python tools/hard_data.py --ai`, also `hard_data_2.py`, `hard_data_3.py`, `hard_data_en.py` (answer keys: no leaks, no damage)
- `python tools/compare_stats.py real_testdata --ai` (the same analysis before and after, and after restoring)
- `python tools/check_uniqueness.py <output>` on a copy, when the levels or the check changed

## Where the code is
`identity.py` who is who, and the questions. `transform.py` table rows and free text. `tables.py` headers. `detect/`
rules and AI. `birthdates.py` is a birth date column plausible. `handlers/` one file per file type, `excel_formulas.py`
stored results. `privacy.py` the levels. `review.py` what was found and what the user decided. `uniqueness.py` the check and the label. `app/` the desktop app. `packaging/` the app bundle and the dmg.

## Next steps
1. Clean-install test of the dmg on a second Mac (Apple chip, macOS 14 or newer).
2. Ideas the owner has seen but not yet chosen: see the roadmap in `README.md`.
