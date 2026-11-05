"""Command-line interface.

    privatier anonymize <folder>             make an anonymised copy
    privatier restore <folder> --key <file>  put real values back into AI results
    privatier show-key <file>                list what each token stands for
    privatier setup-ai                       download the local AI model (once)
"""

from __future__ import annotations

import argparse
import getpass
import os
import sys
from pathlib import Path

from . import __version__
from .engine import KEY_FILE, anonymize_folder, default_paths, restore_folder
from .pseudonyms import Pseudonymizer
from .vault import WrongPasswordError, load_vault


def _password(confirm: bool) -> str:
    env = os.environ.get("PRIVATIER_PASSWORD")
    if env:
        return env
    while True:
        pw = getpass.getpass("Password for the key file: ")
        if len(pw) < 8:
            print("Please use at least 8 characters.")
            continue
        if confirm and getpass.getpass("Repeat password: ") != pw:
            print("Passwords do not match, try again.")
            continue
        return pw


def _refuse_existing(folder: Path) -> None:
    folder = Path(folder).resolve()
    if folder.exists():
        raise FileExistsError(
            f"Output folder already exists: {folder}\n"
            "Privatier never overwrites results. Delete or rename that folder, or choose another with --output."
        )


def _print_summary(title: str, s) -> None:
    print(f"\n{title}")
    print(f"  Output folder: {s.output_dir}")
    print(f"  Files processed: {len(s.processed)}")
    if s.counts:
        print("  Replacements: " + ", ".join(f"{k}={v}" for k, v in sorted(s.counts.items())))
    if s.skipped:
        print(f"\n  Skipped (NOT copied to the output) - {len(s.skipped)}:")
        for f, reason in s.skipped:
            print(f"    - {f}: {reason}")
    if s.errors:
        print(f"\n  Errors (NOT copied to the output) - {len(s.errors)}:")
        for f, err in s.errors:
            print(f"    - {f}: {err}")
    if s.warnings:
        print("\n  Please check:")
        for f, w in s.warnings:
            print(f"    - {f}: {w}")
    if getattr(s, "unknown_tokens", None):
        print("\n  Tokens not found in the key (left unchanged): " + ", ".join(sorted(s.unknown_tokens)))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="privatier", description="Local, auditable pseudonymisation.")
    parser.add_argument("--version", action="version", version=f"privatier {__version__}")
    sub = parser.add_subparsers(dest="command", required=True)

    a = sub.add_parser("anonymize", help="create an anonymised copy of a folder")
    a.add_argument("folder", type=Path)
    a.add_argument("--output", type=Path, help="where to write the anonymised copy")
    a.add_argument("--key-dir", type=Path, help="where to keep key file and audit log (keep private!)")
    a.add_argument("--ai", action="store_true", help="also use the local AI model for name recognition")

    r = sub.add_parser("restore", help="put real values back into files that contain tokens")
    r.add_argument("folder", type=Path)
    r.add_argument("--key", type=Path, required=True, help="the key.vault file from anonymisation")
    r.add_argument("--output", type=Path)

    k = sub.add_parser("show-key", help="list tokens and the real values they stand for")
    k.add_argument("key", type=Path)

    sub.add_parser("setup-ai", help="download the local AI model (needs internet, only once)")

    args = parser.parse_args(argv)
    try:
        if args.command == "anonymize":
            default_out, default_work = default_paths(args.folder)
            _refuse_existing(args.output or default_out)
            key_exists = ((args.key_dir or default_work) / KEY_FILE).exists()
            summary = anonymize_folder(
                args.folder,
                _password(confirm=not key_exists),
                output_dir=args.output,
                work_dir=args.key_dir,
                use_ai=args.ai,
            )
            _print_summary("Anonymisation finished.", summary)
            work = (args.key_dir or default_work).resolve()
            print(f"\n  Key file and audit log (keep private, never upload): {work}")
        elif args.command == "restore":
            _refuse_existing(args.output or args.folder.resolve().with_name(args.folder.resolve().name + "_restored"))
            summary = restore_folder(args.folder, args.key, _password(confirm=False), output_dir=args.output)
            _print_summary("Restore finished.", summary)
        elif args.command == "show-key":
            pseudo = Pseudonymizer.from_dict(load_vault(args.key, _password(confirm=False)))
            for e in pseudo.to_dict()["entries"]:
                print(f"{e['token']}\t{e['original']}")
            if pseudo.people:
                print("\nPeople (full birth dates are only stored here):")
                for p in pseudo.people:
                    births = ", ".join(b["raw"] for b in p["births"]) or "-"
                    ids = ", ".join(value for _, value in p["ids"]) or "-"
                    print(f"{p['token']}\t{p['canonical']}\tborn: {births}\tIDs: {ids}")
        elif args.command == "setup-ai":
            from .detect.gliner_detector import DEFAULT_MODEL, download_model, is_available

            if not is_available():
                print('The AI add-on is not installed. Run:  pip install "privatier[ai]"')
                return 1
            print(f"Downloading {DEFAULT_MODEL} (one time only, about 1.2 GB)...")
            download_model()
            from .detect.gliner_detector import GlinerDetector

            GlinerDetector().detect("Test: Frau Anna Schmidt aus Hamburg.")  # check it really runs offline
            print("Done, the local AI works. Use:  privatier anonymize <folder> --ai")
    except WrongPasswordError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 2
    except (FileNotFoundError, FileExistsError, ValueError, RuntimeError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
