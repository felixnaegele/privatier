"""The most important test: after anonymisation, no sensitive value may remain anywhere."""

import json
import socket
import sys
import zipfile
from pathlib import Path

import pyreadstat
import pytest
from openpyxl import load_workbook

from privatier.engine import AUDIT_FILE, KEY_FILE, anonymize_folder, offline, restore_folder
from privatier.vault import WrongPasswordError

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
from make_sample_data import SENSITIVE, make  # noqa: E402

PASSWORD = "correct horse battery"


@pytest.fixture(scope="module")
def project(tmp_path_factory):
    root = tmp_path_factory.mktemp("work")
    src = make(root / "Studie")
    summary = anonymize_folder(src, PASSWORD)
    return root, src, summary


def all_output_text(folder: Path) -> str:
    """Everything a person (or an AI) could read from the output folder, incl. file names and metadata."""
    chunks = []
    for path in folder.rglob("*"):
        chunks.append(str(path.relative_to(folder)))
        if not path.is_file():
            continue
        if path.suffix in (".docx", ".xlsx"):
            with zipfile.ZipFile(path) as z:
                for name in z.namelist():
                    chunks.append(z.read(name).decode("utf-8", "ignore"))
        elif path.suffix == ".sav":
            df, meta = pyreadstat.read_sav(str(path))
            chunks.append(df.to_csv())
            chunks.append(json.dumps(meta.column_names_to_labels, ensure_ascii=False))
            chunks.append(str(meta.variable_value_labels))
        else:
            raw = path.read_bytes()
            chunks.append(raw.decode("utf-8", "ignore"))
            chunks.append(raw.decode("cp1252", "ignore"))
    return "\n".join(chunks)


def test_no_sensitive_value_left(project):
    root, _, _ = project
    text = all_output_text(root / "Studie_anonymized")
    leaks = [value for value in SENSITIVE if value in text]
    assert leaks == [], f"Sensitive values found in output: {leaks}"


def test_file_names_anonymised(project):
    root, _, _ = project
    names = [p.name for p in (root / "Studie_anonymized").rglob("*")]
    assert not any("Schmidt" in n for n in names)
    assert any(n.startswith("Arztbrief_PERSON_") for n in names)


def test_unsupported_files_are_not_copied(project):
    root, _, summary = project
    out = root / "Studie_anonymized"
    assert not list(out.rglob("*.jpg"))
    assert not list(out.rglob(".DS_Store"))
    assert ("scan_befund.jpg", "file type '.jpg' not supported yet") in summary.skipped
    assert summary.errors == []


def test_key_and_audit_kept_outside_output(project):
    root, _, _ = project
    work = root / "Studie_privatier"
    assert (work / KEY_FILE).exists() and (work / AUDIT_FILE).exists()
    assert not list((root / "Studie_anonymized").rglob("*.vault"))


def test_audit_log_contains_no_sensitive_values(project):
    root, _, _ = project
    audit = (root / "Studie_privatier" / AUDIT_FILE).read_text(encoding="utf-8")
    records = [json.loads(line) for line in audit.splitlines()]
    assert records[0]["event"] == "run_started" and records[-1]["event"] == "run_finished"
    # File names are logged (that is the point of an audit log), the content values are not.
    content_values = [v for v in SENSITIVE if v not in ("Schmidt",)]
    assert [v for v in content_values if v in audit] == []


def test_birth_dates_become_years(project):
    root, _, _ = project
    out = root / "Studie_anonymized" / "daten"
    df, _ = pyreadstat.read_sav(str(out / "fragebogen.sav"))
    assert list(df["gebdat"]) == [1975, 1962, 1958]
    ws = load_workbook(out / "outcomes.xlsx").active
    assert ws["D3"].value == 1980 and ws["D3"].number_format == "General"
    csv = (out / "studie_rohdaten.csv").read_bytes().decode("cp1252")
    assert ";1975;" in csv


def test_same_value_same_token_across_files(project):
    root, _, _ = project
    out = root / "Studie_anonymized"
    docx_xml = zipfile.ZipFile(next(out.glob("Arztbrief_*.docx"))).read("word/document.xml").decode()
    # "Anna Schmidt" appears twice in the letter (body + table) -> same token both times
    import re

    tokens = re.findall(r"Patientin (PERSON_\d+)", docx_xml) + re.findall(r"<w:t>(PERSON_\d+)</w:t>", docx_xml)
    assert len(set(tokens)) == 1


def test_restore_round_trip(project, tmp_path):
    root, _, _ = project
    out = root / "Studie_anonymized"
    letter = zipfile.ZipFile(next(out.glob("Arztbrief_*.docx"))).read("word/document.xml").decode()
    import re

    token = re.search(r"Patientin (PERSON_\d+)", letter).group(1)
    ai_results = tmp_path / "ai_results"
    ai_results.mkdir()
    # The AI may change the token's spelling slightly; restore must still work.
    (ai_results / "summary.md").write_text(
        f"{token} improved. ({token.lower().replace('_', ' ')}) Unknown: PERSON_9999", encoding="utf-8"
    )
    summary = restore_folder(ai_results, root / "Studie_privatier" / KEY_FILE, PASSWORD)
    restored = (tmp_path / "ai_results_restored" / "summary.md").read_text(encoding="utf-8")
    assert restored.startswith("Anna Schmidt improved. (Anna Schmidt)")
    assert "PERSON_9999" in restored and "PERSON_9999" in summary.unknown_tokens


def test_wrong_password(project, tmp_path):
    root, _, _ = project
    (tmp_path / "x").mkdir()
    with pytest.raises(WrongPasswordError):
        restore_folder(tmp_path / "x", root / "Studie_privatier" / KEY_FILE, "wrong password")


def test_refuses_to_overwrite(project):
    _, src, _ = project
    with pytest.raises(FileExistsError):
        anonymize_folder(src, PASSWORD)


def test_network_blocked_while_processing():
    with offline():
        with pytest.raises(OSError):
            socket.create_connection(("example.com", 443), timeout=1)


def test_failed_ai_model_leaves_nothing_behind(tmp_path, monkeypatch):
    import privatier.engine as engine

    def broken(use_ai):
        raise RuntimeError("model could not be loaded")

    monkeypatch.setattr(engine, "build_detectors", broken)
    src = make(tmp_path / "Studie")
    with pytest.raises(RuntimeError):
        anonymize_folder(src, PASSWORD, use_ai=True)
    assert not (tmp_path / "Studie_anonymized").exists()
    assert not (tmp_path / "Studie_privatier").exists()
