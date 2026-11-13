# Privatier

**Work with ChatGPT or Claude on sensitive research data, without the sensitive data ever leaving your computer.**

Privatier makes a protected copy of a project folder on your own laptop. Names, birth dates, patient IDs,
addresses, phone numbers and similar details are replaced by consistent codes (`PERSON_0001`, `ID_0003`, …),
like subject IDs in a clinical trial. You work with the copy in any AI tool. Afterwards Privatier can put the
real values back into the AI's results, using an encrypted key file that never leaves your computer.

## The desktop app (Mac)

Open `Privatier-<version>-arm64.dmg`, drag Privatier onto the Applications folder, and open it from there. It needs a
Mac with an Apple chip (M1 or newer) and macOS 14 or newer. The local AI is part of the app. The app is not signed by
Apple yet: the first start has to be allowed once in System Settings, Privacy & Security ("Open Anyway"). The dmg
contains a short note with the steps.

### One folder per project

The app runs in the macOS App Sandbox. It can only open the folders you add to it, one folder per project, and macOS
itself keeps it away from every other folder. The app also refuses every network connection itself: macOS cannot do
that part, because the window is drawn by WebKit, which needs the network permission to start. There is no "allow access to all files" question:
adding a folder is the permission, and it holds for that folder only.

Everything Privatier makes goes into one folder named `Privatier` inside the project:

```
Studie/                          your project (never changed otherwise)
  Privatier/
    Key - keep private/          key.vault (encrypted), audit.jsonl, privacy_report.txt: never upload
    Studie_pseudonymised/        a protected copy → work with this in ChatGPT / Claude
    Restored/                    results with the real values put back
```

Privatier never reads its own `Privatier` folder as data, so a copy is not processed twice. The key stays with the
project: copy the project folder to another Mac and add it there, and the same key and codes are used. If a project
already has a folder named `Privatier` with your own files in it, the app does not touch it and tells you.

### The window

- **Left, your projects.** "Add folder…" or drop a folder on the window. Removing a project from the list deletes
  nothing.
- **Middle, the files.** Untick a file to leave it out. A file that is not ticked is not read at all, not even to
  tell people apart.
- **Right, the file as its columns.** A table shows one row per column: what kind it is (name, ID, date of birth,
  free text, not identifying) and what it becomes. The arrow opens the values of the column. Every value and every
  column has a tickbox: untick it to keep it as written. A column Privatier leaves alone (shown grey) can be ticked
  too: every value in it then becomes a code. The kind of a column can be corrected in place. A letter has no columns
  and shows one row per kind (names, dates, places). A kept value is your decision: at level 4 it blocks the word
  "anonymous". The edges between the panes and between the column headings can be dragged to change their width; a
  double click puts them back.
- **Spot check.** Type a value that could identify someone and press "Find everywhere". If it is in no file, that is
  the good outcome and nothing changes. If it is still in a file, it is replaced everywhere (by a code like
  `TERM_0001`), and the files are read again, with the local AI if it was off, because the first reading missed it.
- **Protection and issues.** When a project has been read, the protection level comes up by itself, with the
  effect of each level shown before anything is written, followed by the issues (unclear cases). At the top, "No
  issues" or the number of issues shows the state and opens the list; the level button changes the level. An issue
  is also shown as an orange exclamation mark on the column and the value it concerns. Issues can be skipped: what is
  unclear stays apart.
- **Make a copy | Restore.** The switch at the top chooses what the window is for. In "Make a copy", **Make copy…**
  asks for the key password and writes the copy. In "Restore", drop or choose the results the AI gave you, enter the
  password, and they are written with the real values into `Privatier/Restored`.

A project protected with the command line or an earlier version has its key next to the project
(`Studie_privatier/key.vault`). To keep the same codes in the app, make one copy in the app first (this creates the
folders), then replace `Studie/Privatier/Key - keep private/key.vault` by the old `key.vault`.

From the source code, the app starts with `Privatier.command` or `.venv/bin/python -m privatier.app`. Started this
way it is not sandboxed.

## Privacy levels

| | **1. Pseudonymised** (default) | **2. Less detail** | **3. Strongly reduced** | **4. Anonymisation attempt** |
|---|---|---|---|---|
| Names and IDs | Codes | Codes | Random codes | Random codes |
| Key | Kept, reversible | Kept, reversible | None | None |
| Dates | Exact | Month and year | Year | Removed |
| Age | Exact | **Exact** | 10-year bands, 90+ together | 10-year bands, 90+ together |
| Birth date | Year (full date in key) | Year (full date in key) | Decade of birth | Decade of birth |
| Free-text columns | Names replaced | Names replaced | Emptied | Emptied |
| Letters (Word, PDF, text) | Names replaced | Names replaced | Left out and listed | Left out and listed |
| Patients who still stand out | Unchanged | Unchanged | Unchanged | Details blanked, and counted |

On the command line: `privatier anonymize Studie --level 4`.

Before anything is written, the app shows for each level how many patients can still be singled out, and which
columns lose detail. A date that can be read two ways (`03/04/2015`) keeps only its year at level 2. A column judged
to be free text can be kept by ticking it, but the word "anonymous" is then not used.

### When the word "anonymous" is used

Only at level 4, only after checking the files as written, and only if all of this holds:

- Every patient shares sex, age and every date column with at least 4 others (groups of 5), in every table, and
  also when tables are joined by patient code.
- Every table could be checked. "Could not check" never counts as safe.
- No free text, no letters and no key remain, and no macros stay unchecked.
- No file or folder name contains a name or value from the data. File names are never changed, so this blocks the label.

Otherwise the result is "Reduced detail, not anonymous", with the reasons. Even when it passes:

- **Other clinical columns are not compared** unless you tick them, as nearly everyone would look unique otherwise.
  Someone who knows a rare value could still recognise a patient.
- **Row order is unchanged**, so a table sorted by date or name can give hints.
- A number written inside a formula is not looked at.
- **The legal decision is not Privatier's:** ask your data protection officer whether this counts as anonymous.

Levels 3 and 4 lose exact intervals, so survival analysis will not work on those copies. Level 2 allows only rough
intervals, in months. Each run writes `privacy_report.txt` (counts and column names only) next to the audit log.

`tools/check_uniqueness.py <folder>` prints the same check for any folder. It reads Excel, SPSS and CSV, counts
patients rather than rows when a patient column exists, and says so when it can only count rows.

> Status: early prototype (v0.1). Test it with fake data first. Automatic detection is never perfect: always
> look through the anonymised copy before you upload it.

## How it works (command line)

The command line writes next to the folder. The app writes into `Privatier/` inside it, as described above.

```
Studie/                  your original folder (never changed)
Studie_pseudonymised/    the copy at level 1 → work with this in ChatGPT / Claude
Studie_privatier/        KEEP PRIVATE: key.vault (encrypted) + audit.jsonl
```

1. **Anonymise:** `privatier anonymize Studie`
2. Upload files from `Studie_pseudonymised/` to the AI and do your analysis.
3. **Restore (optional):** save the AI's results in a folder, then
   `privatier restore Ergebnisse --key Studie_privatier/key.vault` → `Ergebnisse_restored/`

### Supported files

| Type | What happens |
|---|---|
| Excel `.xlsx` `.xlsm` | all sheets, cells, comments, sheet names, author metadata |
| CSV / TSV | delimiter and encoding detected automatically (also German Excel exports with `;`) |
| SPSS `.sav` `.zsav` | data, variable labels and value labels are kept |
| Word `.docx` | body, tables, text boxes, headers/footers, footnotes, comments, tracked changes, author |
| PDF | text is extracted to an anonymised `name.pdf.md` (scanned PDFs are skipped, see below) |
| Text `.txt` `.md` `.json` `.R` `.py` `.sql` … | plain text |

Files Privatier cannot read (images, scanned PDFs, old `.xls`, …) are **not copied** to the anonymised
folder. They are listed as "skipped", so nothing unchecked slips through.

### How sensitive data is found (German + English)

Detection works in layers:

1. **Column headers:** a column called `Nachname`, `Geburtsdatum`, `Patient ID`, `E-Mail`… is replaced as a
   whole. **Birth dates become the year only** (still useful for age, much less identifying).
2. **Rules** for things with a recognisable shape: emails, phone numbers, dates, IBANs, German health insurance
   numbers (KVNR) and social security numbers, labelled IDs ("Fallnummer: …", "MRN …"), street addresses,
   names after a title or label ("Frau Dr. Schmidt", "Mr. Smith", "Name: Müller, Max").
3. **Local AI (optional, recommended on Apple Silicon M1 or newer):** the
   [GLiNER](https://github.com/urchade/GLiNER) model finds names, organisations and places in free text. It is
   small (about 1.2 GB) and runs on your laptop.
   To protect your data's usefulness, the AI is not used on column headers and labels, and it never replaces
   common research words such as "Patient", "Intervention" or "Kontrolle" (editable list in
   `src/privatier/detect/stopwords.py`).
4. **Known values everywhere:** anything found in step 1–3 is also replaced wherever else it appears in the
   project, e.g. a name from an Excel column that turns up in a Word letter.

### Tables first: what happens to each column

Tables should work with as little input from you as possible. At level 1, every cell in a column that does not
identify anyone comes out exactly as it went in. This table describes level 1.

| Column | What happens |
|---|---|
| Names, IDs, contact details (recognised by the header, German or English) | Replaced by codes |
| Birth date | Reduced to the year; the full date stays in the encrypted key |
| Other dates (surgery, follow-up, death), also when written as text | Kept with day and month, as this detail often matters |
| Categories that repeat a few values (`Placebo`, `T0`, valve types) | Never sent to the AI |
| Free-text columns | Rules everywhere; the AI reads cells of two or more words, and changes are flagged |
| Rows that explain the columns (`(dd/mm/yyyy)`, `(0=no,1=yes)`) | Kept |
| Formulas | Kept, with their stored results, so tools that do not recalculate still see the values |
| Formulas that use an identifying column, also indirectly or through a reference that cannot be traced | Kept, but the stored result is removed as it could reveal the data, and Privatier tells you which column |
| **No header**, and the values look like names, dates or IDs | Replaced, because it could be a birth date or a name, and Privatier asks what it is |
| Header says nothing, but the values look like names | Left as it is, and Privatier asks |

A header can be wrong, so Privatier also checks that a birth date column holds birth dates. It asks if the dates
match another date column, come after a surgery date, lie in the future, or do not fit the age column.

**File and folder names are never changed**, so that you can keep track of your files. Names and dates in them
stay: Privatier tells you when a name from the data appears in one, so you can look before you upload.

### How people are told apart

Privatier never assumes who someone is. It first reads the whole project and then decides from the evidence.
What the data does not settle stays apart and becomes a question.

| Situation | Result |
|---|---|
| Same name and same birth date or same patient ID | One person, one code |
| Same name, different birth date (even in the same year) | Two people, two codes |
| Same name, different patient ID | Two people, two codes |
| Same name and birth date, but different patient IDs | Kept apart, Privatier asks |
| Same name, no birth date or ID | Kept apart, Privatier asks |
| Surname alone ("Mr Smith", "Herr Müller") | A code of its own, Privatier asks whether it is a person in that document |
| Same name with a doctor's title | Kept apart from a patient of that name, unless a birth date or ID in the file confirms it |

- **One switch for the most common question:** `--link-by-name` tells Privatier that in your data an identical
  name is the same person whenever nothing says otherwise. Rows with a differing birth date or ID stay apart.
- **One code per person:** `PERSON_0001` is the full name, `PERSON_0001_F` the first name, `PERSON_0001_L` the
  surname and `PERSON_0001_V1` another spelling (`MUELLER, MAX`). Restoring gives back what was written.
- **Spelling:** `Müller`, `MUELLER` and `Mueller` count as the same name, as do `Weiß` and `Weiss`.
- **Case numbers** (Fallnummer, case ID) do not separate people, since one patient can have several.
- **Birth years count too:** a `Year of birth` column or "Jg. 1961" separates people and links them to a full
  birth date when only one person fits.
- **Ambiguous dates:** `03/04/1975` can be read two ways. A match on either reading links them, and it is flagged.
- **Full birth dates** stay in the encrypted key file. `privatier show-key` lists them, and restoring puts them
  back into a table row when that row still contains the person's code.
- **"Please check" list:** one line per kind of question, using codes only, never real names. The full list is
  in the audit log. Look codes up with `privatier show-key`.

### Safety features

- **Local only:** Privatier blocks all network connections while it processes data.
- **Encrypted key file:** AES-256-GCM, with the key derived from your password (scrypt). Without the password
  the key file is useless. If you lose the password, the codes cannot be reversed (by design).
- **Audit log** (`audit.jsonl`): every run and every file is recorded with SHA-256 fingerprints, counts per
  data type and the codes introduced, but never the sensitive values themselves. Check a file with
  `shasum -a 256 <file>` (Mac) and compare.
- Your original files are never modified, and existing output is never overwritten. The app adds one folder,
  `Privatier`, to the project and writes only there.

## Install (Mac, for testing)

You need Python 3.10 or newer (`python3 --version` in Terminal).

```bash
git clone https://github.com/felixnaegele/privatier.git
cd privatier
python3 -m venv .venv
source .venv/bin/activate
pip install -e .
```

Optional local AI (large download, includes PyTorch):

```bash
pip install -e ".[ai]"
privatier setup-ai          # downloads the model once; afterwards everything runs offline
privatier anonymize Studie --ai
```

Try it with fake data:

```bash
pip install -e ".[dev]"
python tools/make_sample_data.py sample_project
privatier anonymize sample_project
```

## Known limitations (v0.1)

- Free-standing names in text without a title ("Schmidt kam zur Kontrolle") are only found by the local AI
  layer or if the name already appeared elsewhere in the project.
- Two different people with the same name and birth date and no ID cannot be told apart, and count as one person.
- On the command line, questions can only be answered with `--link-by-name`. The app answers them one by one.
- Without the local AI, names and places with no hint around them are missed. In testing on hard data this was
  up to 5 of 39 values, so **use `--ai` for real data**.
- A surname that is also an ordinary word (`Klein`, `Mai`) is replaced wherever it appears capitalised, even
  when it is not the name ("im Mai"). Privatier prefers this to leaving a real name behind.
- After restoring, a birth date can come back in a different written form (`1975-05-12` for `12.05.1975`), and
  IDs and dates in SPSS or Excel files come back as text. The values are the same.
- Dates other than birth dates in spreadsheet columns (surgery, follow-up…) are kept with day and month on purpose. Exact dates can help identify someone, so consider this before you share the data.
- Old Excel `.xls`, scanned PDFs (OCR) and images are not supported yet.
- PDFs become text files; rewriting the PDF itself is planned.
- The app is English only and runs on Macs with an Apple chip. It is not signed by Apple yet, so the first start must be allowed once.
- A postcode on its own (`28203`) is not recognised as identifying.

## Roadmap

- [x] Core engine: Excel, CSV, SPSS, Word, PDF, text; key file; audit log; restore
- [x] Local AI layer (GLiNER) tested on German and English data, and built into the app
- [x] Drag-and-drop desktop app (Mac)
- [x] Review screen: answer questions one by one before export
- [x] Privacy levels, with the effect shown before export
- [ ] Desktop app on Windows
- [ ] Optional date shifting for clinical dates
- [ ] Add-ons: OCR for scanned PDFs, `.xls`, PowerPoint, optional local LLM double-check
- [x] Installer for colleagues (dmg, drag to Applications)
- [x] Review list: keep a value, add a missed word; choose files; restore in the app
- [x] macOS App Sandbox: one folder per project; the app refuses all network connections
- [ ] Clean-install test on a second Mac
- [ ] Paste mode: protect and restore a piece of text through the clipboard, without files
- [ ] Key password in the Mac keychain (Touch ID); remember answers per project
- [ ] Before and after view per file
- [ ] German interface
- [ ] Signing by Apple, so the first start needs no extra step

## Build the app

```bash
.venv/bin/python -m pip install -e ".[app,ai,build]"
privatier setup-ai                      # the model must be on this Mac: it is copied into the app
sh packaging/build_app.sh               # dist/Privatier.app, a self-test, then dist/Privatier-<version>-arm64.dmg
```

`--app-only` and `--dmg-only` run one half, and `--no-sandbox` builds an app without the sandbox for finding errors. The build takes about 6 minutes and the app is about 1.8 GB, most of it
the AI. `dist/Privatier.app/Contents/MacOS/Privatier --self-test` checks a finished app without opening a window: it
makes mock files, protects them with the AI, and restores them. `tools/ui_demo.py` shows the screen in a browser
with made-up data.

## For developers

```
src/privatier/
  detect/       detectors: patterns.py (rules), gliner_detector.py (local AI)
  handlers/     one file per file type; add new file types here
  tables.py     recognising sensitive columns by header
  transform.py  anonymise / restore logic
  identity.py   who is who: telling people apart by name, birth date and ID
  pseudonyms.py consistent codes, known-value propagation
  vault.py      encrypted key file
  audit.py      audit log
  privacy.py    the four levels, what each does to a value
  review.py     what was found, and what the user decided about it (keep a value, add a word)
  project.py    the Privatier folder inside a project: key, copies, restored results
  uniqueness.py who can be singled out, what each level would change, when "anonymous" may be said
  app/          the desktop app: service.py (logic), window.py (the window), ui.html (the screen), projects.py and
                access.py (the folders the app may open), selftest.py
  engine.py     folder processing, network blocking
  cli.py        command line
packaging/      builds Privatier.app and the dmg
tests/          run with: pytest
tools/          hard_data*.py: messy German and English test data with answer keys; add --ai to use the local model
                compare_stats.py: proves an analysis gives the same answer before and after, on your own folder
```

## Licence

Privatier is free and open source under the [Apache License 2.0](LICENSE): anyone may use, study, change and
share it, including at work. It comes **without any warranty**. Privatier helps you remove identifying
information, but it does not by itself make a use of data compliant with GDPR, HIPAA or your institution's
rules. You remain responsible for checking the anonymised output and for following those rules.

The optional local AI model is downloaded separately and has its own licence; check it on its model page
before relying on it.
