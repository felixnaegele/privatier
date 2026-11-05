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
- **No information lost:** every cell in a non-identifying column comes out exactly as it went in.
- **Dates other than birth dates** (surgery, follow-up, death) keep day and month. Birth dates become the year, with the
  full date kept in the encrypted key.
- **File and folder names are never changed**, so users can keep track of their files.
- **Do not test for the sake of testing.** Tell the owner when the necessary tests are done, and move on.

## Practical notes
- Never print cell values from `real_testdata/` (gitignored): only headers, counts and shapes. Test on copies filled with
  mock data, except for tools that only print verdicts.
- This session type cannot write to `.git`: give the owner the commit and push commands to run in Terminal, naming the
  paths (`git add README.md CLAUDE.md src tests tools`), never `git add .`.
- Use `.venv/bin/python -m pytest` and `.venv/bin/python -m pip`.

## Checks to run after changing the engine
- `pytest`
- `python tools/hard_data.py --ai`, also `hard_data_2.py`, `hard_data_3.py`, `hard_data_en.py` (answer keys: no leaks, no damage)
- `python tools/compare_stats.py real_testdata --ai` (the same analysis before and after, and after restoring)

## Where the code is
`identity.py` who is who. `transform.py` table rows and free text. `tables.py` headers. `detect/` rules and AI.
`birthdates.py` is a birth date column plausible. `handlers/` one file per file type, `excel_formulas.py` stored results.

## Next steps
1. Desktop app (drag and drop) with a review screen, so that questions can be answered one by one. Today only
   `--link-by-name` answers them.
2. Installer for colleagues, then a clean-install test on Mac and Windows.
