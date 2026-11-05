# Privatier

**Work with ChatGPT or Claude on sensitive research data, without the sensitive data ever leaving your computer.**

Privatier makes an anonymised copy of a project folder on your own laptop. Names, birth dates, patient IDs,
addresses, phone numbers and similar details are replaced by consistent codes (`PERSON_0001`, `ID_0003`, …),
like subject IDs in a clinical trial. You work with the anonymised copy in any AI tool. Afterwards Privatier
can put the real values back into the AI's results, using an encrypted key file that never leaves your computer.

> Status: early prototype (v0.1). Test it with fake data first. Automatic detection is never perfect: always
> look through the anonymised copy before you upload it.

## How it works

```
Studie/                  your original folder (never changed)
Studie_anonymized/       safe copy → work with this in ChatGPT / Claude
Studie_privatier/        KEEP PRIVATE: key.vault (encrypted) + audit.jsonl
```

1. **Anonymise:** `privatier anonymize Studie`
2. Upload files from `Studie_anonymized/` to the AI and do your analysis.
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

Tables should work with as little input from you as possible. Every cell in a column that does not identify
anyone comes out exactly as it went in.

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
- The original folder is never modified, and existing output is never overwritten.

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
- Questions can only be answered with `--link-by-name` so far. Answering them one by one is planned for the review
  screen, and flagged people cannot be merged or split by hand yet.
- Without the local AI, names and places with no hint around them are missed. In testing on hard data this was
  up to 5 of 39 values, so **use `--ai` for real data**.
- A surname that is also an ordinary word (`Klein`, `Mai`) is replaced wherever it appears capitalised, even
  when it is not the name ("im Mai"). Privatier prefers this to leaving a real name behind.
- After restoring, a birth date can come back in a different written form (`1975-05-12` for `12.05.1975`), and
  IDs and dates in SPSS or Excel files come back as text. The values are the same.
- Dates other than birth dates in spreadsheet columns (surgery, follow-up…) are kept with day and month on purpose. Exact dates can help identify someone, so consider this before you share the data.
- Old Excel `.xls`, scanned PDFs (OCR) and images are not supported yet.
- PDFs become text files; rewriting the PDF itself is planned.
- No graphical app yet: drag-and-drop for Mac/Windows is the next step.

## Roadmap

- [x] Core engine: Excel, CSV, SPSS, Word, PDF, text; key file; audit log; restore
- [ ] Test the local AI layer (GLiNER) on a Mac with German and English documents
- [ ] Drag-and-drop desktop app (Mac, Windows)
- [ ] Review screen: see and correct every detection before export
- [ ] Optional date shifting for clinical dates
- [ ] Add-ons: OCR for scanned PDFs, `.xls`, PowerPoint, optional local LLM double-check
- [ ] Installer for colleagues

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
  engine.py     folder processing, network blocking
  cli.py        command line
tests/          run with: pytest
tools/          hard_data*.py: messy German and English test data with answer keys; add --ai to use the local model
```

## Licence

Privatier is free and open source under the [Apache License 2.0](LICENSE): anyone may use, study, change and
share it, including at work. It comes **without any warranty**. Privatier helps you remove identifying
information, but it does not by itself make a use of data compliant with GDPR, HIPAA or your institution's
rules. You remain responsible for checking the anonymised output and for following those rules.

The optional local AI model is downloaded separately and has its own licence; check it on its model page
before relying on it.
