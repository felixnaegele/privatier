"""Processes a whole project folder.

Anonymising works in two passes over all files:
  1. Find sensitive values everywhere (nothing is written yet).
  2. Write the anonymised copy. Now every value found in pass 1 is also
     replaced wherever else it appears (e.g. a name from an Excel column that
     shows up again in a Word letter).

The original folder is never changed. Files Privatier cannot read are NOT
copied to the output; they are listed as skipped, so nothing unchecked can
slip through.
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
from .pseudonyms import Pseudonymizer
from .transform import Anonymizer, Restorer, Transformer
from .vault import load_vault, save_vault

KEY_FILE = "key.vault"
AUDIT_FILE = "audit.jsonl"


@dataclass
class Summary:
    output_dir: Path
    processed: list[str] = field(default_factory=list)
    skipped: list[tuple[str, str]] = field(default_factory=list)
    errors: list[tuple[str, str]] = field(default_factory=list)
    warnings: list[tuple[str, str]] = field(default_factory=list)
    counts: Counter[str] = field(default_factory=Counter)
    unknown_tokens: Counter[str] = field(default_factory=Counter)


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
def default_paths(input_dir: Path) -> tuple[Path, Path]:
    input_dir = input_dir.resolve()
    return (
        input_dir.with_name(input_dir.name + "_anonymized"),
        input_dir.with_name(input_dir.name + "_privatier"),
    )


def _list_files(root: Path) -> list[Path]:
    files = []
    for path in sorted(root.rglob("*")):
        rel = path.relative_to(root)
        if any(part.startswith(".") or part.startswith("~$") for part in rel.parts):
            continue  # hidden files (.DS_Store) and Office lock files
        if path.is_file() and not path.is_symlink():
            files.append(path)
    return files


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


# --------------------------------------------------------------------------- anonymise
def anonymize_folder(
    input_dir: Path,
    password: str,
    output_dir: Path | None = None,
    work_dir: Path | None = None,
    use_ai: bool = False,
    detectors: list | None = None,
) -> Summary:
    input_dir = Path(input_dir).resolve()
    default_out, default_work = default_paths(input_dir)
    output_dir = Path(output_dir or default_out).resolve()
    work_dir = Path(work_dir or default_work).resolve()

    if not input_dir.is_dir():
        raise FileNotFoundError(f"Folder not found: {input_dir}")
    if output_dir.exists():
        raise FileExistsError(f"Output folder already exists, refusing to overwrite: {output_dir}")
    if output_dir.is_relative_to(input_dir) or work_dir.is_relative_to(input_dir):
        raise ValueError("Output and key folders must be outside the input folder.")
    if work_dir.is_relative_to(output_dir):
        raise ValueError("The key folder must not be inside the anonymised folder.")

    key_path = work_dir / KEY_FILE
    # Re-using an existing key keeps tokens stable when a project is anonymised again.
    pseudo = Pseudonymizer.from_dict(load_vault(key_path, password)) if key_path.exists() else Pseudonymizer()

    if detectors is None:
        with offline():  # the AI model must load from disk only
            detectors = build_detectors(use_ai)
    work_dir.mkdir(parents=True, exist_ok=True)  # only once everything is ready
    anon = Anonymizer(pseudo, detectors)
    audit = AuditLog(work_dir / AUDIT_FILE)
    summary = Summary(output_dir)
    files = _list_files(input_dir)
    audit.run_started(
        "anonymize",
        input=str(input_dir),
        output=str(output_dir),
        detectors=anon.detector_names + ["known"],
        files=len(files),
    )

    with offline():
        # Pass 1: collect sensitive values and the evidence about who is who.
        for path in files:
            handler = handler_for(path)
            if handler is None:
                continue
            anon.current_file = str(path.relative_to(input_dir))
            anon.file_name(path.stem)
            for part in path.relative_to(input_dir).parent.parts:
                anon.file_name(part)
            try:
                handler.process(path, None, anon)
            except Exception:
                pass  # reported in pass 2
        anon.finish_collecting()
        project_review = [("(whole project)", note) for note in dict.fromkeys(anon.registry.review)]
        summary.warnings.extend(project_review)
        for file, note in project_review:
            audit.write("identity_review", file=file, note=note)

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
            anon.reset_file_stats()
            out_rel = _output_rel_path(rel, handler.output_name(path), anon)
            dst = _unique(output_dir / out_rel)
            dst.parent.mkdir(parents=True, exist_ok=True)
            try:
                handler.process(path, dst, anon)
            except Exception as exc:  # never leave a half-written file behind
                dst.unlink(missing_ok=True)
                summary.errors.append((str(rel), str(exc)))
                audit.write("file_error", file=str(rel), handler=handler.name, error=str(exc), sha256=sha256(path))
                continue
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
                tokens=sorted(anon.tokens),
                warnings=anon.warnings,
            )

    save_vault(key_path, pseudo.to_dict(), password)
    audit.write(
        "run_finished",
        action="anonymize",
        processed=len(summary.processed),
        skipped=len(summary.skipped),
        errors=len(summary.errors),
        replacements=dict(summary.counts),
        tokens_in_key=len(pseudo),
        key_file_sha256=sha256(key_path),
    )
    return summary


# --------------------------------------------------------------------------- restore
def restore_folder(input_dir: Path, key_path: Path, password: str, output_dir: Path | None = None) -> Summary:
    input_dir = Path(input_dir).resolve()
    key_path = Path(key_path).resolve()
    output_dir = Path(output_dir or input_dir.with_name(input_dir.name + "_restored")).resolve()
    if output_dir.exists():
        raise FileExistsError(f"Output folder already exists, refusing to overwrite: {output_dir}")

    pseudo = Pseudonymizer.from_dict(load_vault(key_path, password))
    restorer = Restorer(pseudo)
    audit = AuditLog(key_path.parent / AUDIT_FILE)
    summary = Summary(output_dir)
    files = _list_files(input_dir)
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
