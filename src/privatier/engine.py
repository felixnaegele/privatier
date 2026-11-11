"""Processes a whole project folder.

Anonymising works in two passes over all files:
  1. Find sensitive values everywhere (nothing is written yet).
  2. Write the anonymised copy. Now every value found in pass 1 is also
     replaced wherever else it appears (e.g. a name from an Excel column that
     shows up again in a Word letter).

The original folder is never changed. Files Privatier cannot read are NOT
copied to the output; they are listed as skipped, so nothing unchecked can
slip through.

scan_folder() does the same without writing anything: it finds the questions to ask before an export.
"""

from __future__ import annotations

import socket
from collections import Counter
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path

from .audit import AuditLog, sha256
from .detect import PatternDetector
from .handlers import handler_for
from .handlers.base import LeftOut
from .identity import Decisions, Question
from .privacy import LEVELS
from .pseudonyms import KnownValueDetector, Pseudonymizer
from .review import Finding, Review
from .transform import Anonymizer, Restorer, Transformer
from .uniqueness import (
    FolderCheck, Table, Verdict, build_plan, check_tables, list_files, read_tables, select_files, verdict,
)
from .vault import load_vault, save_vault

KEY_FILE = "key.vault"
AUDIT_FILE = "audit.jsonl"
REPORT_FILE = "privacy_report.txt"
_LETTERS = {"docx", "pdf", "text"}


@dataclass
class Summary:
    output_dir: Path
    processed: list[str] = field(default_factory=list)
    skipped: list[tuple[str, str]] = field(default_factory=list)
    errors: list[tuple[str, str]] = field(default_factory=list)
    warnings: list[tuple[str, str]] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)  # for information, nothing to decide
    counts: Counter[str] = field(default_factory=Counter)
    unknown_tokens: Counter[str] = field(default_factory=Counter)
    level: int = 1
    check: FolderCheck | None = None
    verdict: Verdict | None = None
    report_path: Path | None = None
    key_dir: Path | None = None  # where the key, the audit log and the report are
    kept_values: int = 0  # values the user said to leave, that were left in a written file
    kept_places: int = 0
    added_terms: int = 0  # words the user added
    added_found: int = 0  # how many of them occur in the files
    added_places: int = 0  # places replaced because of them, that would have stayed otherwise


@dataclass
class Scan:
    """What a folder holds, before anything is written."""

    folder: Path
    tables: list[Table]
    other_files: list[str]
    questions: list[Question]
    warnings: list[tuple[str, str]]
    named_files: list[str]
    unsupported: list[str]
    used_ai: bool
    findings: list[Finding] = field(default_factory=list)  # real values: for the user's screen only


# --------------------------------------------------------------------------- safety
class NetworkBlockedError(OSError):
    pass


@contextmanager
def offline():
    """Block every network connection while sensitive data is being processed."""

    def blocked(*args, **kwargs):
        raise NetworkBlockedError("Privatier blocks all network access while processing data.")

    saved = (socket.socket.connect, socket.socket.connect_ex, socket.create_connection, socket.getaddrinfo)
    socket.socket.connect = blocked
    socket.socket.connect_ex = blocked
    socket.create_connection = blocked
    socket.getaddrinfo = blocked
    try:
        yield
    finally:
        socket.socket.connect, socket.socket.connect_ex, socket.create_connection, socket.getaddrinfo = saved


# --------------------------------------------------------------------------- helpers
def default_paths(input_dir: Path, level: int = 1) -> tuple[Path, Path]:
    input_dir = input_dir.resolve()
    return (
        input_dir.with_name(input_dir.name + LEVELS[level].folder_suffix),
        input_dir.with_name(input_dir.name + "_privatier"),
    )


_list_files = list_files


def _output_rel_path(rel: Path, out_name: str, t: Transformer) -> Path:
    """File and folder names can contain names too ("Arztbrief_Mueller.docx")."""
    parts = [t.file_name(p) for p in rel.parent.parts]
    stem, dot, ext = out_name.partition(".")
    return Path(*parts, t.file_name(stem) + dot + ext)


def _unique(path: Path) -> Path:
    if not path.exists():
        return path
    stem, suffix = path.name.split(".", 1) if "." in path.name else (path.name, "")
    n = 2
    while True:
        candidate = path.with_name(f"{stem}_{n}" + (f".{suffix}" if suffix else ""))
        if not candidate.exists():
            return candidate
        n += 1


def build_detectors(use_ai: bool) -> list:
    detectors: list = [PatternDetector()]
    if use_ai:
        from .detect.gliner_detector import GlinerDetector

        detectors.append(GlinerDetector())
    return detectors


def _first_pass(anon: Anonymizer, files: list[Path], input_dir: Path) -> None:
    """Collect sensitive values and the evidence about who is who."""
    for path in files:
        handler = handler_for(path)
        if handler is None or (handler.name in _LETTERS and not anon.level.keeps_letters):
            continue
        anon.current_file = str(path.relative_to(input_dir))
        try:
            handler.process(path, None, anon)
        except Exception:
            pass  # reported in pass 2
    anon.finish_collecting()


def _named_files(pseudo: Pseudonymizer, files: list[Path], input_dir: Path, terms: list[str] | None = None) -> list[str]:
    known = KnownValueDetector(pseudo, terms)
    return [str(f.relative_to(input_dir)) for f in files if known.detect(str(f.relative_to(input_dir)))]


def _anonymizer(
    pseudo: Pseudonymizer, detectors: list, link_by_name: bool, plan, decisions, ai_cache, review: Review | None,
    files: list[Path], input_dir: Path,
) -> Anonymizer:
    anon = Anonymizer(pseudo, detectors, link_by_name, plan, decisions, ai_cache, review)
    if review is not None and review.keep:
        # A value of an identifying column is never left as written. Which values these are must be known
        # before the first file is read, so the tables are read once more, without looking for anything.
        before = Anonymizer(Pseudonymizer(), [], link_by_name, plan, decisions)
        _first_pass(before, files, input_dir)
        anon.columns = before.columns
    return anon


def scan_folder(
    input_dir: Path,
    use_ai: bool = False,
    detectors: list | None = None,
    link_by_name: bool = False,
    decisions: Decisions | None = None,
    ai_cache: dict | None = None,
    review: Review | None = None,
    only: list[Path] | None = None,
) -> Scan:
    """Everything an export would ask about and replace, without writing a single file.

    With `only`, just these files of the folder are read: the others are not listed and not used as evidence."""
    input_dir = Path(input_dir).resolve()
    if not input_dir.is_dir():
        raise FileNotFoundError(f"Folder not found: {input_dir}")
    with offline():
        if detectors is None:
            detectors = build_detectors(use_ai)
        files = select_files(input_dir, only)
        anon = _anonymizer(Pseudonymizer(), detectors, link_by_name, None, decisions, ai_cache, review, files, input_dir)
        _first_pass(anon, files, input_dir)
        warnings: list[tuple[str, str]] = []
        for path in files:  # as pass 2, but nothing is written
            handler = handler_for(path)
            if handler is None:
                continue
            anon.current_file = str(path.relative_to(input_dir))
            anon.reset_file_stats()
            try:
                handler.process(path, None, anon)
            except Exception:
                continue
            anon.file_done()
            warnings.extend((anon.current_file, w) for w in anon.warnings)
        tables, others = read_tables(input_dir, (decisions or Decisions()).columns, only)
        named = _named_files(anon.pseudo, files, input_dir, anon.terms)
    return Scan(
        input_dir, tables, others, list(anon.registry.questions.values()), warnings, named,
        [str(f.relative_to(input_dir)) for f in files if handler_for(f) is None],
        any(d.name == "ner" for d in detectors),
        anon.findings(),
    )


# --------------------------------------------------------------------------- anonymise
def anonymize_folder(
    input_dir: Path,
    password: str = "",
    output_dir: Path | None = None,
    work_dir: Path | None = None,
    use_ai: bool = False,
    detectors: list | None = None,
    link_by_name: bool = False,
    level: int = 1,
    decisions: Decisions | None = None,
    extra_columns: set | None = None,
    keep_text: set | None = None,
    ai_cache: dict | None = None,
    review: Review | None = None,
    only: list[Path] | None = None,
    key_dir: Path | None = None,
) -> Summary:
    """`key_dir` is another name for `work_dir`: where the key, the audit log and the report go.

    With `only`, just these files of the folder are read and written. The copy and the key may then lie
    inside the folder, next to the file, as long as none of the chosen files is in them."""
    settings = LEVELS[level]
    input_dir = Path(input_dir).resolve()
    default_out, default_work = default_paths(input_dir, level)
    output_dir = Path(output_dir or default_out).resolve()
    work_dir = Path(key_dir or work_dir or default_work).resolve()
    decisions = decisions or Decisions()

    if not input_dir.is_dir():
        raise FileNotFoundError(f"Folder not found: {input_dir}")
    if output_dir.exists():
        raise FileExistsError(f"Output folder already exists, refusing to overwrite: {output_dir}")
    files = select_files(input_dir, only)
    if only is None:
        if output_dir.is_relative_to(input_dir) or work_dir.is_relative_to(input_dir):
            raise ValueError("Output and key folders must be outside the input folder.")
    elif any(f.resolve().is_relative_to(output_dir) or f.resolve().is_relative_to(work_dir) for f in files):
        raise ValueError("A chosen file lies inside the output or key folder.")
    if work_dir.is_relative_to(output_dir):
        raise ValueError("The key folder must not be inside the anonymised folder.")

    key_path = work_dir / KEY_FILE
    if settings.keeps_key:
        # Re-using an existing key keeps tokens stable when a project is anonymised again.
        pseudo = Pseudonymizer.from_dict(load_vault(key_path, password)) if key_path.exists() else Pseudonymizer()
    else:
        pseudo = Pseudonymizer(random_codes=True)  # an old key must not fit, and no new one is kept

    if detectors is None:
        with offline():  # the AI model must load from disk only
            detectors = build_detectors(use_ai)
    plan = None
    if level > 1:
        with offline():
            tables, _ = read_tables(input_dir, decisions.columns, only)
        plan = build_plan(tables, level, extra_columns, keep_text)
    work_dir.mkdir(parents=True, exist_ok=True)  # only once everything is ready
    with offline():
        anon = _anonymizer(pseudo, detectors, link_by_name, plan, decisions, ai_cache, review, files, input_dir)
    audit = AuditLog(work_dir / AUDIT_FILE)
    summary = Summary(output_dir, level=level, key_dir=work_dir)
    reviewed = {}
    if review is not None:  # numbers only: what was kept or added never goes into the log
        reviewed = {"marked_to_keep": len(review.keep), "added_terms": len(anon.terms)}
    audit.run_started(
        "anonymize",
        input=str(input_dir),
        output=str(output_dir),
        detectors=anon.detector_names + ["known"],
        files=len(files),
        level=level,
        **reviewed,
    )

    with offline():
        _first_pass(anon, files, input_dir)
        project_review = [("(whole project)", note) for note in dict.fromkeys(anon.registry.review)]
        summary.warnings.extend(project_review)
        for file, note in project_review:
            audit.write("identity_review", file=file, note=note)
        for note in dict.fromkeys(anon.registry.settled):
            audit.write("identity_settled", note=note)
        named = _named_files(pseudo, files, input_dir, anon.terms)
        if named:
            summary.notes.append(
                f"{len(named)} file or folder name(s) contain a name or value from the data. Names are kept on "
                "purpose: look at them before you upload."
            )

        # Pass 2: write the anonymised copy.
        output_dir.mkdir(parents=True)
        for path in files:
            rel = path.relative_to(input_dir)
            handler = handler_for(path)
            anon.current_file = str(rel)
            if handler is None:
                reason = f"file type '{path.suffix or '(none)'}' not supported yet"
                summary.skipped.append((str(rel), reason))
                audit.write("file_skipped", file=str(rel), reason=reason, sha256=sha256(path))
                continue
            if handler.name in _LETTERS and not settings.keeps_letters:
                reason = "text and letters are left out at this level, as they cannot be checked"
                summary.skipped.append((str(rel), reason))
                audit.write("file_skipped", file=str(rel), reason=reason)
                continue
            anon.reset_file_stats()
            # File and folder names stay as they are, so that people can keep track of their files.
            dst = _unique(output_dir / rel.parent / handler.output_name(path))
            dst.parent.mkdir(parents=True, exist_ok=True)
            try:
                handler.process(path, dst, anon)
            except LeftOut as exc:
                dst.unlink(missing_ok=True)
                summary.skipped.append((str(rel), str(exc)))
                audit.write("file_skipped", file=str(rel), reason=str(exc))
                continue
            except Exception as exc:  # never leave a half-written file behind
                dst.unlink(missing_ok=True)
                summary.errors.append((str(rel), str(exc)))
                audit.write("file_error", file=str(rel), handler=handler.name, error=str(exc), sha256=sha256(path))
                continue
            anon.file_done()
            summary.processed.append(str(rel))
            summary.counts.update(anon.stats)
            for w in anon.warnings:
                summary.warnings.append((str(rel), w))
            audit.write(
                "file_anonymized",
                file=str(rel),
                output=str(dst.relative_to(output_dir)),
                handler=handler.name,
                sha256_input=sha256(path),
                sha256_output=sha256(dst),
                replacements=dict(anon.stats),
                tokens=sorted(anon.tokens) if settings.keeps_key else [],
                warnings=anon.warnings,
            )

        # The check reads what was really written, not what should have been.
        written, others = read_tables(output_dir, decisions.columns)
        summary.check = check_tables(written, others, None, extra_columns)

    unchecked = [f"{f}: {w}" for f, w in summary.warnings if "macros" in w]
    if review is not None:
        summary.kept_values, summary.kept_places = anon.kept_values, anon.kept_places
        summary.added_terms, summary.added_found, summary.added_places = len(anon.terms), anon.added_found, anon.added_places
    if summary.kept_places:
        # Privatier did not look at these any further, so it cannot say that nothing identifying is left.
        unchecked.append(
            f"{summary.kept_values} value(s) you marked as not sensitive were left as written, in "
            f"{summary.kept_places} place(s). They are still in the copy, so it cannot be called anonymous."
        )
        summary.notes.append(
            f"{summary.kept_values} value(s) you marked as not sensitive were left as written, in "
            f"{summary.kept_places} place(s)."
        )
    if summary.added_terms:
        summary.notes.append(
            f"{summary.added_found} of the {summary.added_terms} word(s) you added occur in the files. Because of "
            f"them, {summary.added_places} more place(s) were replaced."
        )
    summary.verdict = verdict(level, summary.check, len(named), unchecked)
    if anon.kept_date_columns:
        summary.notes.append(
            f"{len(anon.kept_date_columns)} date column(s) other than birth dates were kept with day and month."
        )
        audit.write("date_columns_kept", columns=sorted(anon.kept_date_columns))
    if settings.keeps_key:
        save_vault(key_path, pseudo.to_dict(), password)
    summary.report_path = work_dir / REPORT_FILE
    summary.report_path.write_text(report_text(summary, anon), encoding="utf-8")
    audit.write(
        "run_finished",
        action="anonymize",
        level=level,
        processed=len(summary.processed),
        skipped=len(summary.skipped),
        errors=len(summary.errors),
        replacements=dict(summary.counts),
        tokens_in_key=len(pseudo) if settings.keeps_key else 0,
        key_file_sha256=sha256(key_path) if settings.keeps_key else None,
        label=summary.verdict.label,
        **(
            {
                "kept_values": summary.kept_values, "kept_places": summary.kept_places,
                "added_terms": summary.added_terms, "added_terms_found": summary.added_found,
                "added_places": summary.added_places,
            }
            if review is not None
            else {}
        ),
    )
    return summary


def report_text(summary: Summary, anon: Anonymizer | None = None) -> str:
    """Counts and column names only, so that it can be read without seeing any patient."""
    check, result = summary.check, summary.verdict
    lines = [
        f"Privatier privacy report: level {summary.level}, {LEVELS[summary.level].name}",
        f"Output folder: {summary.output_dir}",
        f"Result: {result.label}",
        *(f"  - {reason}" for reason in result.reasons),
        "",
        "Checked on the files as written:",
    ]
    for table in [*check.tables, *([check.linked] if check.linked else [])]:
        if table.status == "could_not_check":
            lines.append(f"  {table.title}: COULD NOT CHECK ({table.reason})")
        elif table.status == "nothing_to_compare":
            lines.append(f"  {table.title}: no sex, age or date columns left to compare")
        else:
            lines.append(
                f"  {table.title}: {table.singled_out} of {table.total} {table.unit} can be singled out "
                f"({table.percent:.1f}%), {table.in_small_group} in a group smaller than 5. "
                f"Compared: {', '.join(table.characteristics)}"
            )
    if summary.skipped:
        lines += ["", "Left out:", *(f"  {file}: {reason}" for file, reason in summary.skipped)]
    if summary.kept_places or summary.added_terms:  # numbers only, never the values
        lines += ["", "Your choices on the review screen:"]
        if summary.kept_places:
            lines.append(
                f"  Left as written, because you marked them as not sensitive: {summary.kept_values} value(s), "
                f"in {summary.kept_places} place(s)."
            )
        if summary.added_terms:
            lines.append(
                f"  Words you added: {summary.added_terms}, of which {summary.added_found} occur in the files. "
                f"Because of them, {summary.added_places} more place(s) were replaced."
            )
    return "\n".join(lines) + "\n"


# --------------------------------------------------------------------------- restore
def restore_folder(
    input_dir: Path, key_path: Path, password: str, output_dir: Path | None = None, only: list[Path] | None = None
) -> Summary:
    """With `only`, just these files of the folder are restored."""
    input_dir = Path(input_dir).resolve()
    key_path = Path(key_path).resolve()
    output_dir = Path(output_dir or input_dir.with_name(input_dir.name + "_restored")).resolve()
    if output_dir.exists():
        raise FileExistsError(f"Output folder already exists, refusing to overwrite: {output_dir}")

    files = select_files(input_dir, only)
    if only is not None and any(f.resolve().is_relative_to(output_dir) for f in files):
        raise ValueError("A chosen file lies inside the output folder.")
    pseudo = Pseudonymizer.from_dict(load_vault(key_path, password))
    restorer = Restorer(pseudo)
    audit = AuditLog(key_path.parent / AUDIT_FILE)
    summary = Summary(output_dir, key_dir=key_path.parent)
    audit.run_started("restore", input=str(input_dir), output=str(output_dir), files=len(files))

    with offline():
        output_dir.mkdir(parents=True)
        for path in files:
            rel = path.relative_to(input_dir)
            handler = handler_for(path)
            if handler is None:
                summary.skipped.append((str(rel), f"file type '{path.suffix or '(none)'}' not supported yet"))
                audit.write("file_skipped", file=str(rel), sha256=sha256(path))
                continue
            restorer.reset_file_stats()
            out_rel = _output_rel_path(rel, handler.output_name(path), restorer)
            dst = _unique(output_dir / out_rel)
            dst.parent.mkdir(parents=True, exist_ok=True)
            try:
                handler.process(path, dst, restorer)
            except Exception as exc:
                dst.unlink(missing_ok=True)
                summary.errors.append((str(rel), str(exc)))
                audit.write("file_error", file=str(rel), error=str(exc))
                continue
            summary.processed.append(str(rel))
            summary.counts.update(restorer.stats)
            audit.write(
                "file_restored",
                file=str(rel),
                output=str(dst.relative_to(output_dir)),
                sha256_input=sha256(path),
                sha256_output=sha256(dst),
                restored=dict(restorer.stats),
            )
    summary.unknown_tokens = restorer.unknown
    audit.write(
        "run_finished",
        action="restore",
        processed=len(summary.processed),
        restored=dict(summary.counts),
        unknown_tokens=sorted(restorer.unknown),
    )
    return summary
