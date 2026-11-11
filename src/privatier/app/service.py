"""What the window asks for, without anything that depends on the window itself.

Every method returns plain data that can go to the screen. Real names appear only in the questions: they
are needed to answer them, stay on this computer's screen, and are never written to a file.
"""

from __future__ import annotations

from pathlib import Path

from ..cli import _grouped_questions
from ..detect import gliner_detector
from ..engine import KEY_FILE, anonymize_folder, build_detectors, default_paths, offline, restore_folder, scan_folder
from ..handlers import handler_for
from ..identity import Decisions, Question
from ..privacy import CHANGE_WORDS, LEVELS, MIN_GROUP
from ..review import MIN_TERM_LENGTH, Review
from ..uniqueness import FolderCheck, Table, TableCheck, build_plan, check_tables, read_tables, select_files, verdict
from ..vault import WrongPasswordError

_ASKED_ALREADY = (" may be ", "may belong to", "may refer to", "looks like names", "look like names")
_LETTER_TYPES = {".docx", ".pdf", ".txt", ".md", ".json", ".r", ".py", ".sql", ".rmd", ".log", ".xml", ".html", ".yaml", ".yml", ".tex"}


_TYPE_LABELS = {
    "PERSON": "Name", "BIRTH_DATE": "Date of birth", "DATE": "Date", "ID": "ID", "EMAIL": "Email address",
    "PHONE": "Phone number", "ADDRESS": "Address", "LOCATION": "Place", "ORG": "Organisation", "IBAN": "IBAN",
    "KVNR": "Insurance number", "SSN": "Social security number", "URL": "Web address", "TERM": "Word added by you",
}
_TYPE_ORDER = list(_TYPE_LABELS)


def ai_model_ready() -> bool:
    """The add-on is installed and the model is on this computer. Nothing is downloaded here."""
    return gliner_detector.model_ready()


def _selection(paths) -> tuple[Path, list[Path] | None, str]:
    """One folder, or files that lie in one folder. Returns the folder, the files, and a name for the result."""
    if isinstance(paths, str):
        paths = [paths]
    chosen = [Path(p).expanduser().resolve() for p in paths or [] if p]
    if not chosen:
        raise ValueError("Nothing was chosen.")
    if any(not c.exists() for c in chosen):
        raise ValueError("This could not be found any more. Please choose it again.")
    folders = [c for c in chosen if c.is_dir()]
    if folders:
        if len(chosen) > 1:
            raise ValueError("Please choose one folder, or one or more files from the same folder.")
        return folders[0], None, folders[0].name
    if len({c.parent for c in chosen}) > 1:
        raise ValueError("These files are in different folders. Please choose files from one folder, or the whole folder.")
    name = chosen[0].stem if len(chosen) == 1 else f"{chosen[0].stem}_and_{len(chosen) - 1}_more"
    return chosen[0].parent, sorted(chosen), name


def _free(path: Path) -> Path:
    candidate, n = path, 2
    while candidate.exists():
        candidate = path.with_name(f"{path.name}_{n}")
        n += 1
    return candidate


def _ref(item: list) -> tuple[str, str, int]:
    return (str(item[0]), str(item[1]), int(item[2]))


def _table_json(table: TableCheck) -> dict:
    return {
        "title": table.title,
        "status": table.status,
        "reason": table.reason,
        "unit": table.unit,
        "total": table.total,
        "singled_out": table.singled_out,
        "percent": round(table.percent, 1),
        "in_small_group": table.in_small_group,
        "percent_small": round(table.percent_small, 1),
        "characteristics": table.characteristics,
        "blanked_rows": table.blanked_rows,
        "not_compared": table.not_compared,
    }


def _check_json(check: FolderCheck) -> dict:
    worst = check.worst
    tables = [*check.tables, *([check.linked] if check.linked else [])]
    return {
        "worst": _table_json(worst) if worst else None,
        "tables": [_table_json(t) for t in tables],
        "could_not_check": [_table_json(t) for t in check.could_not_check],
    }


class AppSession:
    def __init__(self) -> None:
        self.folder: Path | None = None
        self.questions: dict[str, Question] = {}
        self.tables: list[Table] = []
        self.others: list[str] = []
        self.named: list[str] = []
        self.warnings: list[tuple[str, str]] = []
        self.unsupported: list[str] = []
        self.detectors: list | None = None
        self.ai_cache: dict = {}
        self.status = ""
        self._read_with: dict | None = None
        self.only: list[Path] | None = None
        self.base: Path | None = None  # what the output folders are named after
        self.use_ai = False
        self.choice = Review()

    # -- reading a folder ----------------------------------------------------
    def scan(self, paths, use_ai: bool) -> dict:
        try:
            folder, only, name = _selection(paths)
        except ValueError as exc:
            return {"error": str(exc)}
        if only and all(handler_for(f) is None for f in only):
            return {"error": "Privatier cannot read this kind of file. It reads Excel, SPSS, CSV, Word, PDF and text files."}
        self.__init__()
        self.folder, self.only, self.use_ai = folder, only, bool(use_ai)
        self.base = folder if only is None else folder / name
        if use_ai:
            self.status = "Loading the local AI model"
            with offline():
                self.detectors = build_detectors(True)
        else:
            self.detectors = build_detectors(False)
        return self._read()

    def review(self, keep: list, extra: list) -> dict:
        """Reads again with the user's choices: values to leave as they are, and words that were missed."""
        if self.folder is None:
            return {"error": "Please choose a folder first."}
        self.choice = self._review(keep, extra)
        return self._read()

    @staticmethod
    def _review(keep, extra) -> Review:
        words: list[str] = []
        for word in extra or []:
            word = str(word).strip()
            if len(word) >= MIN_TERM_LENGTH and word not in words:
                words.append(word)
        return Review(keep={str(k) for k in keep or []}, extra=words)

    def _read(self) -> dict:
        folder = self.folder
        self.status = "Reading your files"
        try:
            scan = scan_folder(
                folder, detectors=self.detectors, ai_cache=self.ai_cache, review=self.choice, only=self.only
            )
        finally:
            self.status = ""
        self.tables, self.others = scan.tables, scan.other_files
        self._read_with = {}
        self.named, self.warnings, self.unsupported = scan.named_files, scan.warnings, scan.unsupported
        self.questions = {q.id: q for q in scan.questions}
        key_dir = default_paths(self.base)[1]
        return {
            "folder": self.base.name if self.only is None else (self.only[0].name if len(self.only) == 1 else f"{len(self.only)} files"),
            "path": str(folder),
            "single": self.only is not None,
            "used_ai": scan.used_ai,
            "tables": len([t for t in self.tables if not t.problem]),
            "other_files": len(self.others) - len(self.unsupported),
            "unsupported": self.unsupported,
            "named_files": len(self.named),
            "questions": [self._question_json(q) for q in scan.questions],
            "findings": self._findings_json(scan.findings),
            "notes": self._notes(),
            "columns": self._columns(),
            "has_key": (key_dir / KEY_FILE).exists(),
            "levels": [
                {"number": n, "name": level.name, "summary": level.summary, "keeps_key": level.keeps_key}
                for n, level in LEVELS.items()
            ],
            "preview": self.preview({}, [], []),
        }

    @staticmethod
    def _findings_json(findings) -> list[dict]:
        def order(f):
            return (_TYPE_ORDER.index(f.type) if f.type in _TYPE_ORDER else len(_TYPE_ORDER), f.type, -f.count, f.value.lower())

        return [
            {
                "id": f.id, "type": f.type, "label": _TYPE_LABELS.get(f.type, f.type.replace("_", " ").capitalize()),
                "value": f.value, "count": f.count, "files": f.files, "source": f.source, "can_keep": f.can_keep,
                "kept": f.kept, "already_replaced": f.already_replaced,
            }
            for f in sorted(findings, key=order)
        ]

    def _question_json(self, question: Question) -> dict:
        letters_only = bool(question.files) and all(Path(f).suffix.lower() in _LETTER_TYPES for f in question.files)
        return {
            "id": question.id,
            "kind": question.kind,
            "text": question.text,
            "options": [{"value": value, "label": label} for value, label in question.options],
            "files": sorted(question.files),
            "letters_only": letters_only,
        }

    def _notes(self) -> list[str]:
        """What is worth knowing but has no answer. Whatever became a question is not repeated."""
        return _grouped_questions([(f, w) for f, w in self.warnings if not any(p in w for p in _ASKED_ALREADY)])

    def _columns(self) -> list[dict]:
        """Columns the user can add to the check, such as a rare diagnosis."""
        return [
            {"ref": [t.file, t.name, c.index], "table": t.title, "header": c.header}
            for t in self.tables
            for c in t.columns
            if c.kind in (None, "text") and not c.patient
        ]

    # -- what each level would do --------------------------------------------
    def _decisions(self, answers: dict) -> Decisions:
        decisions = Decisions()
        for question_id, value in (answers or {}).items():
            question = self.questions.get(question_id)
            if question is not None:
                decisions.apply(question, value)
        return decisions

    def _tables_with(self, decisions: Decisions) -> list[Table]:
        """A column's answer can change what it counts as, then it is read again."""
        if decisions.columns != self._read_with:
            with offline():
                self.tables, self.others = read_tables(self.folder, decisions.columns, only=self.only)
            self._read_with = dict(decisions.columns)
        return self.tables

    def preview(self, answers: dict, ticked: list, kept_text: list) -> dict:
        tables = self._tables_with(self._decisions(answers))
        extra = {_ref(item) for item in ticked or []}
        keep = {_ref(item) for item in kept_text or []}
        return {str(number): self._preview_level(number, tables, extra, keep) for number in LEVELS}

    def _preview_level(self, number: int, tables: list[Table], extra: set, keep: set) -> dict:
        level = LEVELS[number]
        plan = build_plan(tables, number, extra, keep)
        others = [f for f in self.others if f not in self.unsupported] if level.keeps_letters else []
        check = check_tables(tables, others, plan, extra)
        result = verdict(number, check, len(self.named), self._macro_notes())
        lost = []
        for table in tables:
            for column in table.columns:
                ref = (table.file, table.name, column.index)
                action = plan.actions.get(ref)
                if action:
                    lost.append({
                        "ref": list(ref), "table": table.title, "header": column.header,
                        "change": CHANGE_WORDS[action], "free_text": False if action != "empty" else True,
                    })
                elif column.kind == "text" and ref in keep:
                    lost.append({
                        "ref": list(ref), "table": table.title, "header": column.header,
                        "change": "kept on your request", "free_text": True, "kept": True,
                    })
            if (table.file, table.name) in plan.removed_tables:
                lost.append({"ref": None, "table": table.title, "header": "(whole table)", "change": f"left out: {table.problem}", "free_text": False})
        left_out = []
        if not level.keeps_letters:
            left_out = [f for f in self.others if f not in self.unsupported]
        return {
            **_check_json(check),
            "lost": lost,
            "left_out": left_out,
            "blanked_rows": sum(len(rows) for rows in plan.blanks.values()),
            "label": result.label,
            "anonymous": result.anonymous,
            "reasons": result.reasons,
            "min_group": MIN_GROUP,
        }

    def _macro_notes(self) -> list[str]:
        return [f"{f}: {w}" for f, w in self.warnings if "macros" in w]

    # -- writing the copy ----------------------------------------------------
    def _free_output(self, level: int) -> Path:
        return _free(default_paths(self.base, level)[0])

    def export(self, level: int, password: str, answers: dict, ticked: list, kept_text: list, keep=None, extra=None) -> dict:
        level = int(level)
        if LEVELS[level].keeps_key and len(password or "") < 8:
            return {"error": "Please use a password of at least 8 characters for the key."}
        self.status = "Writing the copy and checking it"
        try:
            summary = anonymize_folder(
                self.folder,
                password or "",
                output_dir=self._free_output(level),
                detectors=self.detectors,
                level=level,
                decisions=self._decisions(answers),
                extra_columns={_ref(item) for item in ticked or []},
                keep_text={_ref(item) for item in kept_text or []},
                ai_cache=self.ai_cache,
                review=self._review(keep, extra),
                only=self.only,
                key_dir=default_paths(self.base)[1],
            )
        except WrongPasswordError:
            return {"error": "This is not the password of the existing key for this folder."}
        finally:
            self.status = ""
        return {
            **_check_json(summary.check),
            "output": str(summary.output_dir),
            "label": summary.verdict.label,
            "anonymous": summary.verdict.anonymous,
            "reasons": summary.verdict.reasons,
            "processed": len(summary.processed),
            "skipped": [{"file": f, "reason": r} for f, r in summary.skipped],
            "errors": [{"file": f, "reason": "this file could not be processed, so it is not in the copy"} for f, _ in summary.errors],
            "notes": summary.notes,
            "report": str(summary.report_path),
            "key_dir": str(summary.report_path.parent) if LEVELS[level].keeps_key else None,
            "kept": summary.kept_values,
        }

    # -- putting the real values back ----------------------------------------
    @staticmethod
    def _suggested_key(folder: Path) -> str | None:
        """A key right next to the results, if there is exactly one. Otherwise the user chooses."""
        found = sorted({*folder.parent.glob(f"*_privatier/{KEY_FILE}"), *folder.glob(f"*_privatier/{KEY_FILE}")})
        return str(found[0]) if len(found) == 1 else None

    def restore_info(self, paths) -> dict:
        try:
            folder, only, name = _selection(paths)
        except ValueError as exc:
            return {"error": str(exc)}
        files = [f for f in select_files(folder, only) if handler_for(f) is not None]
        if not files:
            return {"error": "There is no file here that Privatier can read."}
        shown = folder.name if only is None else (only[0].name if len(only) == 1 else f"{len(only)} files")
        return {"name": shown, "files": len(files), "suggested_key": self._suggested_key(folder)}

    def restore(self, paths, key_path: str, password: str) -> dict:
        try:
            folder, only, name = _selection(paths)
        except ValueError as exc:
            return {"error": str(exc)}
        key = Path(key_path or "").expanduser()
        if not key_path or not key.is_file():
            return {"error": "Please choose the key file (key.vault). It is in the folder ending in _privatier."}
        if not password:
            return {"error": "Please enter the password of the key."}
        base = folder if only is None else folder / name
        output = _free(base.with_name(base.name + "_restored"))
        self.status = "Putting the real values back"
        try:
            summary = restore_folder(folder, key, password, output_dir=output, only=only)
        except WrongPasswordError:
            return {"error": "This password does not open this key file."}
        except ValueError:
            return {"error": "This is not a Privatier key file. Please choose the key.vault file from the folder ending in _privatier."}
        finally:
            self.status = ""
        return {
            "output": str(summary.output_dir),
            "restored": len(summary.processed),
            "values": sum(summary.counts.values()),
            "unknown": len(summary.unknown_tokens),
            "skipped": [{"file": f, "reason": r} for f, r in summary.skipped],
            "errors": [{"file": f, "reason": "this file could not be read, so it is not in the restored copy"} for f, _ in summary.errors],
        }
