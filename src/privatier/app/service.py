"""What the window asks for, without anything that depends on the window itself.

Every method returns plain data that can go to the screen. Real names appear only in the questions: they
are needed to answer them, stay on this computer's screen, and are never written to a file.
"""

from __future__ import annotations

from pathlib import Path

from ..cli import _grouped_questions
from ..detect import gliner_detector
from ..engine import KEY_FILE, anonymize_folder, build_detectors, offline, restore_folder, scan_folder
from ..handlers import handler_for
from ..identity import Decisions, Question
from ..privacy import CHANGE_WORDS, LEVELS, MIN_GROUP
from ..project import PrivatierFolderError, ensure_privatier_dir, key_dir, restored_dir
from ..review import MIN_TERM_LENGTH, Review
from ..uniqueness import FolderCheck, Table, TableCheck, build_plan, check_tables, read_tables, select_files, verdict
from ..vault import WrongPasswordError
from .projects import ProjectStore

_ASKED_ALREADY = (" may be ", "may belong to", "may refer to", "looks like names", "look like names")
_LETTER_TYPES = {".docx", ".pdf", ".txt", ".md", ".json", ".r", ".py", ".sql", ".rmd", ".log", ".xml", ".html", ".yaml", ".yml", ".tex"}


_TYPE_LABELS = {
    "PERSON": "Name", "BIRTH_DATE": "Date of birth", "DATE": "Date", "ID": "ID", "EMAIL": "Email address",
    "PHONE": "Phone number", "ADDRESS": "Address", "LOCATION": "Place", "ORG": "Organisation", "IBAN": "IBAN",
    "KVNR": "Insurance number", "SSN": "Social security number", "URL": "Web address", "TERM": "Word added by you",
}
_TYPE_ORDER = list(_TYPE_LABELS)
_GROUP_LABELS = {
    "PERSON": "Names", "BIRTH_DATE": "Dates of birth", "DATE": "Dates", "ID": "IDs", "EMAIL": "Email addresses",
    "PHONE": "Phone numbers", "ADDRESS": "Addresses", "LOCATION": "Places", "ORG": "Organisations", "IBAN": "IBANs",
    "KVNR": "Insurance numbers", "SSN": "Social security numbers", "URL": "Web addresses", "TERM": "Words added by you",
}
# What a table column counts as. "KEEP" is how the page knows a column nothing is done to.
_COLUMN_KINDS = {
    "PERSON": "Name", "ID": "ID", "ADDRESS": "Address", "EMAIL": "Email address", "PHONE": "Phone number",
    "BIRTH_DATE": "Date of birth", "BIRTH_YEAR": "Year of birth", "DATE": "Date", "AGE": "Age", "SEX": "Sex",
    "TEXT": "Free text", "PLAIN": "Not identifying",
}
_CHOICE_LABELS = {
    "PERSON": "Name", "ID": "ID", "DOB": "Date of birth", "KEEP_DATES": "Date, not a birth date", "KEEP": "Not identifying",
}
_TABLE_TYPES = {".xlsx", ".xlsm", ".csv", ".tsv", ".sav", ".zsav"}
_DOCUMENT_TYPES = {".docx", ".pdf"}
_GONE = "This folder cannot be reached any more. Add it again with Add folder."


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


def _column_becomes(column) -> str:
    """Short enough for the narrow column of the list."""
    if column.kind == "TEXT":
        return "found parts become codes" if column.values else "nothing found inside"
    if column.kind == "DATE" and column.becomes.startswith("dates stay"):
        return "stays as it is"
    return column.becomes.split(" (")[0]


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
    def __init__(self, store: ProjectStore | None = None) -> None:
        self._store = store
        self._reset()

    @property
    def store(self) -> ProjectStore:
        if self._store is None:
            self._store = ProjectStore()
        return self._store

    def _reset(self) -> None:
        self.project_id: str | None = None
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
        self.only: list[Path] | None = None  # None: every file of the project
        self.use_ai = False
        self.choice = Review()
        self.column_choices: dict[tuple, str] = {}  # what the user said a column is
        self.ticked_columns: set[tuple] = set()  # columns the user ticked to replace: every value becomes a code

    # -- the list of project folders -----------------------------------------
    def projects(self) -> list[dict]:
        return self.store.listing()

    def add_project(self, paths) -> dict:
        if isinstance(paths, str):
            paths = [paths]
        paths = [p for p in paths or [] if p]
        if len(paths) != 1:
            return {"error": "Please add one folder at a time."}
        try:
            added = self.store.add(paths[0])
        except ValueError as exc:
            return {"error": str(exc)}
        return {"projects": self.projects(), "added": added}

    def remove_project(self, project_id: str) -> dict:
        self.store.remove(project_id)
        if project_id == self.project_id:
            self._reset()
        return {"projects": self.projects()}

    # -- reading a project ---------------------------------------------------
    def open_project(self, project_id: str, use_ai: bool) -> dict:
        folder = self.store.path(project_id)
        if folder is None:
            return {"error": _GONE}
        self._reset()
        self.project_id, self.folder, self.use_ai = project_id, folder, bool(use_ai)
        if use_ai:
            self.status = "Loading the local AI model"
            try:
                with offline():
                    self.detectors = build_detectors(True)
            finally:
                self.status = ""
        else:
            self.detectors = build_detectors(False)
        return self._read()

    def set_files(self, selected: list) -> dict:
        """Which files go into the copy. The others are not read at all, not even to tell people apart."""
        if self.folder is None:
            return {"error": "Please choose a project first."}
        if not self.folder.is_dir():
            return {"error": _GONE}
        readable = [f for f in select_files(self.folder, None) if handler_for(f) is not None]
        wanted = {str(s) for s in selected or []}
        chosen = [f for f in readable if f.relative_to(self.folder).as_posix() in wanted]
        if not chosen:
            return {"error": "Tick at least one file."}
        self.only = None if len(chosen) == len(readable) else chosen
        return self._read()

    def review(self, keep: list, extra: list) -> dict:
        """Reads again with the user's choices: values to leave as they are, and words that were missed."""
        if self.folder is None:
            return {"error": "Please choose a project first."}
        self.choice = self._review(keep, extra)
        return self._read()

    def spot_check(self, keep: list, extra: list, term: str) -> dict:
        """The user looks for one value Privatier may have missed. Not in any file: good, nothing changes. Already
        replaced: nothing was missed. Found and still there: it is added to the words to replace, and because the
        first reading missed it, the files are read again, with the local AI if it was off."""
        if self.folder is None:
            return {"error": "Please choose a project first."}
        term = str(term or "").strip()
        if len(term) < MIN_TERM_LENGTH:
            return {"error": f"Please enter at least {MIN_TERM_LENGTH} characters."}
        before = list(extra or [])
        self.choice = self._review(keep, before + [term])
        result = self._read()
        hit = next(
            (f for f in result["findings"] if f["source"] == "added" and f["value"].lower() == term.lower()), None
        )
        places = hit["count"] if hit else 0
        if not places:
            # The word changes nothing, so it does not go on the list. The files as read stay valid.
            self.choice = self._review(keep, before)
            result["findings"] = [f for f in result["findings"] if f is not hit]
            result["spot"] = {"term": term, "found": False, "already": bool(hit and hit["already_replaced"])}
            return result
        ai_now = False
        if not self.use_ai and ai_model_ready():
            self.status = "Loading the local AI model"
            try:
                with offline():
                    self.detectors = build_detectors(True)
            finally:
                self.status = ""
            self.use_ai = ai_now = True
            result = self._read()
        result["spot"] = {"term": term, "found": True, "places": places, "ai_now": ai_now, "ai_used": result["used_ai"]}
        return result

    def set_column(self, ref, value, by_tick: bool = False) -> dict:
        """The user says what a column is (a name, an ID, not identifying ...). None takes the choice back.
        by_tick: the user ticked Replace on a column nothing was done to, so every value becomes a code."""
        if self.folder is None:
            return {"error": "Please choose a project first."}
        key = _ref(ref)
        self.ticked_columns.discard(key)
        if value in _CHOICE_LABELS:
            self.column_choices[key] = str(value)
            if by_tick and value == "ID":
                self.ticked_columns.add(key)
        else:
            self.column_choices.pop(key, None)
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
                folder, detectors=self.detectors, ai_cache=self.ai_cache, review=self.choice, only=self.only,
                decisions=Decisions(columns=dict(self.column_choices)),
            )
        finally:
            self.status = ""
        self.tables, self.others = scan.tables, scan.other_files
        self._read_with = dict(self.column_choices)
        self.named, self.warnings, self.unsupported = scan.named_files, scan.warnings, scan.unsupported
        self.questions = {q.id: q for q in scan.questions}
        return {
            "project": self.project_id,
            "folder": folder.name,
            "path": str(folder),
            "single": False,
            "used_ai": scan.used_ai,
            "tables": len([t for t in self.tables if not t.problem]),
            "other_files": len(self.others) - len(self.unsupported),
            "unsupported": self.unsupported,
            "named_files": len(self.named),
            "files": self._files_json(scan),
            "questions": [self._question_json(q) for q in scan.questions],
            "findings": self._findings_json(scan.findings, scan.questions),
            "outline": self._outline_json(scan),
            "notes": self._notes(),
            "columns": self._columns(),
            "has_key": (key_dir(folder) / KEY_FILE).exists(),
            "levels": [
                {"number": n, "name": level.name, "summary": level.summary, "keeps_key": level.keeps_key}
                for n, level in LEVELS.items()
            ],
            "preview": self.preview({}, [], []),
        }

    def _files_json(self, scan) -> list[dict]:
        """Every file of the project, also the unticked ones and those Privatier cannot read."""
        chosen = None if self.only is None else {f.relative_to(self.folder).as_posix() for f in self.only}
        found: dict[str, int] = {}
        for finding in scan.findings:
            if finding.count or finding.kept:
                for file in finding.files:
                    found[file] = found.get(file, 0) + 1
        asked: dict[str, int] = {}
        for question in scan.questions:
            for file in question.files:
                asked[file] = asked.get(file, 0) + 1
        rows = []
        for path in select_files(self.folder, None):
            rel = path.relative_to(self.folder).as_posix()
            suffix = path.suffix.lower()
            readable = handler_for(path) is not None
            kind = "other" if not readable else "table" if suffix in _TABLE_TYPES else "document" if suffix in _DOCUMENT_TYPES else "text"
            selected = readable and (chosen is None or rel in chosen)
            rows.append({
                "path": rel, "name": path.name, "kind": kind,
                "found": found.get(rel, 0) if selected else 0,
                "questions": asked.get(rel, 0) if selected else 0,
                "status": "ready" if readable else "left_out",
                "reason": None if readable else "Privatier cannot read this kind of file yet, so it is left out of the copy.",
                "selected": selected,
            })
        return rows

    def _outline_json(self, scan) -> dict:
        """Each file as its columns (tables) and kinds of findings (text), with the values that sit there."""
        asked_columns: dict[tuple, list[str]] = {}
        asked_findings: dict[str, list[str]] = {}
        for question in scan.questions:
            for ref in question.columns:
                asked_columns.setdefault(tuple(ref), []).append(question.id)
            for finding_id in question.finding_ids:
                asked_findings.setdefault(finding_id, []).append(question.id)
        becomes = {f.id: f.becomes.split(" (")[0] for f in scan.findings}

        def values(pairs) -> list[dict]:
            return [{"id": finding_id, "count": count} for finding_id, count in pairs]

        def group_becomes(pairs) -> str:
            said = {becomes.get(finding_id, "") for finding_id, _ in pairs}
            return said.pop() if len(said) == 1 else "see each value"

        out = {}
        for file in scan.outline:
            tables = []
            for table in file.tables:
                tables.append({
                    "name": table.name,
                    "problem": table.problem,
                    "columns": [
                        {
                            "ref": list(c.ref), "header": c.header,
                            "kind": "KEEP" if c.kind == "PLAIN" else c.kind,
                            "kind_label": "Replaced by you" if tuple(c.ref) in self.ticked_columns
                            else _COLUMN_KINDS.get(c.kind, c.kind.replace("_", " ").capitalize()),
                            "becomes": "a code for each value" if tuple(c.ref) in self.ticked_columns else _column_becomes(c),
                            "values": values(c.values),
                            "total_values": c.total_values,
                            "choices": [{"value": v, "label": _CHOICE_LABELS[v]} for v in c.choices if v in _CHOICE_LABELS],
                            "decided": c.decided,
                            "tick": tuple(c.ref) in self.ticked_columns,
                            "questions": asked_columns.get(tuple(c.ref), []),
                        }
                        for c in table.columns
                    ],
                })
            groups = [
                {
                    "type": entity_type,
                    "label": _GROUP_LABELS.get(entity_type, entity_type.replace("_", " ").capitalize()),
                    "becomes": group_becomes(pairs),
                    "values": values(pairs),
                    "questions": [],
                }
                for entity_type, pairs in sorted(
                    file.groups, key=lambda g: _TYPE_ORDER.index(g[0]) if g[0] in _TYPE_ORDER else len(_TYPE_ORDER)
                )
            ]
            out[file.file] = {"tables": tables, "groups": groups}
        return out

    @staticmethod
    def _findings_json(findings, questions=()) -> list[dict]:
        asked: dict[str, list[str]] = {}
        for question in questions:
            for finding_id in question.finding_ids:
                asked.setdefault(finding_id, []).append(question.id)

        def order(f):
            return (_TYPE_ORDER.index(f.type) if f.type in _TYPE_ORDER else len(_TYPE_ORDER), f.type, -f.count, f.value.lower())

        return [
            {
                "id": f.id, "type": f.type, "label": _TYPE_LABELS.get(f.type, f.type.replace("_", " ").capitalize()),
                "value": f.value, "count": f.count, "files": f.files, "source": f.source, "can_keep": f.can_keep,
                "keep_reason": "" if f.can_keep else "A word you added is always replaced. Remove the word to keep it.",
                "questions": asked.get(f.id, []),
                "kept": f.kept, "already_replaced": f.already_replaced, "becomes": f.becomes.split(" (")[0],  # "a name code": the column is narrow
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
            "columns": [list(ref) for ref in sorted(question.columns, key=str)],
            "finding_ids": sorted(question.finding_ids),
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
        decisions.columns.update(self.column_choices)  # what the user set on the column itself counts last
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
        label, anonymous, reasons = result.label, result.anonymous, list(result.reasons)
        if anonymous and self.choice.keep:
            # The copy as written decides in the end. Until then a kept value speaks against the word.
            label, anonymous = "Reduced detail, not anonymous", False
            reasons.append("You chose to keep values as written: they would be in the copy.")
        return {
            **_check_json(check),
            "lost": lost,
            "left_out": left_out,
            "blanked_rows": sum(len(rows) for rows in plan.blanks.values()),
            "label": label,
            "anonymous": anonymous,
            "reasons": reasons,
            "min_group": MIN_GROUP,
        }

    def _macro_notes(self) -> list[str]:
        return [f"{f}: {w}" for f, w in self.warnings if "macros" in w]

    # -- writing the copy ----------------------------------------------------
    def export(self, level: int, password: str, answers: dict, ticked: list, kept_text: list, keep=None, extra=None) -> dict:
        level = int(level)
        if LEVELS[level].keeps_key and len(password or "") < 8:
            return {"error": "Please use a password of at least 8 characters for the key."}
        if self.folder is None or not self.folder.is_dir():
            return {"error": _GONE}
        try:
            home = ensure_privatier_dir(self.folder)
        except PrivatierFolderError as exc:
            return {"error": str(exc)}
        self.status = "Writing the copy and checking it"
        try:
            summary = anonymize_folder(
                self.folder,
                password or "",
                output_dir=_free(home / f"{self.folder.name}{LEVELS[level].folder_suffix}"),
                detectors=self.detectors,
                level=level,
                decisions=self._decisions(answers),
                extra_columns={_ref(item) for item in ticked or []},
                keep_text={_ref(item) for item in kept_text or []},
                ai_cache=self.ai_cache,
                review=self._review(keep, extra),
                only=self.only,
                key_dir=key_dir(self.folder),
            )
        except WrongPasswordError:
            return {"error": "This is not the password of the existing key for this folder."}
        finally:
            self.status = ""
        return {
            **_check_json(summary.check),
            "output": str(summary.output_dir),
            "output_name": summary.output_dir.name,
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
    def restore_info(self, paths) -> dict:
        try:
            folder, only, name = _selection(paths)
        except ValueError as exc:
            return {"error": str(exc)}
        files = [f for f in select_files(folder, only) if handler_for(f) is not None]
        if not files:
            return {"error": "There is no file here that Privatier can read."}
        shown = folder.name if only is None else (only[0].name if len(only) == 1 else f"{len(only)} files")
        return {"name": shown, "files": len(files)}

    def restore(self, paths, password: str) -> dict:
        """Puts the real values back, with the key of the open project. The result goes into the project."""
        if self.folder is None or not self.folder.is_dir():
            return {"error": _GONE}
        key = key_dir(self.folder) / KEY_FILE
        if not key.is_file():
            return {"error": "This project has no key yet. A key is made with the first copy at level 1 or 2."}
        if not password:
            return {"error": "Please enter the password of the key."}
        try:
            folder, only, name = _selection(paths)
            ensure_privatier_dir(self.folder)
            output = _free(restored_dir(self.folder) / f"{name}_restored")
        except ValueError as exc:  # also PrivatierFolderError
            return {"error": str(exc)}
        self.status = "Putting the real values back"
        try:
            summary = restore_folder(folder, key, password, output_dir=output, only=only)
        except WrongPasswordError:
            return {"error": "This is not the password of this project's key."}
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
