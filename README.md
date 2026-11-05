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
   small (a few hundred MB) and runs on your laptop.
4. **Known values everywhere:** anything found in step 1–3 is also replaced wherever else it appears in the
   project, e.g. a name from an Excel column that turns up in a Word letter, or in a file name.

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
- Dates other than birth dates in spreadsheet columns (admission, visit…) are kept; Privatier warns about them.
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
  pseudonyms.py consistent codes, known-value propagation
  vault.py      encrypted key file
  audit.py      audit log
  engine.py     folder processing, network blocking
  cli.py        command line
tests/          run with: pytest
```
