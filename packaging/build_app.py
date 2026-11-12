"""Builds Privatier.app and Privatier-<version>-arm64.dmg.

    .venv/bin/python packaging/build_app.py              app, self-test, then dmg
    .venv/bin/python packaging/build_app.py --app-only   app and self-test, no dmg
    .venv/bin/python packaging/build_app.py --no-sandbox     debug app without the App Sandbox (no dmg)
    .venv/bin/python packaging/build_app.py --dmg-only   only the dmg, from the existing dist/Privatier.app
    --no-selftest                                         skip the self-test after building the app

Output goes to dist/ (the app and the dmg). Temporary files go to build/. Both folders are not committed.
"""

from __future__ import annotations

import argparse
import os
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PKG = ROOT / "packaging"
BUILD = ROOT / "build"
DIST = ROOT / "dist"
APP = DIST / "Privatier.app"
STAGE = BUILD / "ai_stage"
HUB = Path(os.environ.get("HF_HUB_CACHE") or Path(os.environ.get("HF_HOME", Path.home() / ".cache" / "huggingface")) / "hub")

MODELS = {  # model folder -> files that must be in the snapshot
    "models--urchade--gliner_multi_pii-v1": ["gliner_config.json", "pytorch_model.bin"],
    "models--microsoft--mdeberta-v3-base": ["config.json", "spm.model", "tokenizer_config.json"],
}


def version() -> str:
    text = (ROOT / "src" / "privatier" / "__init__.py").read_text()
    return re.search(r'__version__\s*=\s*"([^"]+)"', text).group(1)


def say(text: str) -> None:
    print(f"\n==> {text}", flush=True)


def size_of(path: Path) -> str:
    total = sum(f.stat().st_size for f in path.rglob("*") if f.is_file() and not f.is_symlink()) if path.is_dir() else path.stat().st_size
    return f"{total / 1e6:,.0f} MB"


def stage_ai() -> None:
    """Copies the AI model into build/ai_stage as real files (the cache holds links into a blobs folder)."""
    say("Preparing the AI model (copying real files, about 1.1 GB)")
    if STAGE.exists():
        shutil.rmtree(STAGE)
    hub_out, legal = STAGE / "hub", STAGE / "legal"
    legal.mkdir(parents=True)
    for folder, needed in MODELS.items():
        src = HUB / folder
        if not src.is_dir():
            sys.exit(f"The AI model is missing: {src}\nRun once:  .venv/bin/privatier setup-ai   (needs internet)")
        rev = (src / "refs" / "main").read_text().strip()
        snap = src / "snapshots" / rev
        missing = [n for n in needed if not (snap / n).exists()]
        if missing:
            sys.exit(f"{folder} is incomplete, missing: {missing}")
        dst = hub_out / folder
        (dst / "refs").mkdir(parents=True)
        (dst / "refs" / "main").write_text(rev)
        shutil.copytree(snap, dst / "snapshots" / rev, symlinks=False)  # symlinks=False: follow the links, copy the files
        if (src / ".no_exist").is_dir():
            shutil.copytree(src / ".no_exist", dst / ".no_exist")
    card = HUB / "models--urchade--gliner_multi_pii-v1" / "snapshots"
    for readme in card.glob("*/README.md"):
        shutil.copy(readme.resolve(), legal / "gliner_multi_pii-v1-model-card.md")
    for name in ("LICENSE", "NOTICE"):
        shutil.copy(ROOT / name, legal / name)
    shutil.copy(PKG / "THIRD_PARTY_NOTICES.txt", legal / "THIRD_PARTY_NOTICES.txt")
    print("staged:", size_of(STAGE))


def build_app(sandbox: bool = True) -> None:
    if not (PKG / "icon.icns").exists() or not (PKG / "dmg_background.tiff").exists():
        say("Drawing the icon")
        subprocess.run([sys.executable, str(PKG / "make_icon.py")], check=True)
    stage_ai()
    say("Building Privatier.app with PyInstaller (takes several minutes)")
    if APP.exists():
        shutil.rmtree(APP)
    subprocess.run(
        [sys.executable, "-m", "PyInstaller", "--noconfirm", "--clean", "--distpath", str(DIST),
         "--workpath", str(BUILD / "pyinstaller"), str(PKG / "Privatier.spec")],
        check=True, cwd=ROOT,
        env={**os.environ, "PYINSTALLER_CONFIG_DIR": str(BUILD / "pyinstaller_cache")},  # keeps everything inside build/
    )
    # The spec also leaves a plain folder next to the app; it is not needed.
    shutil.rmtree(DIST / "Privatier", ignore_errors=True)
    sign(sandbox)


def sign(sandbox: bool = True) -> None:
    say("Signing (ad hoc, so the app starts on Apple Silicon)")
    # 1. All nested code first, without entitlements (entitlements belong only on the main program).
    subprocess.run(["codesign", "--force", "--deep", "--sign", "-", "--timestamp=none", str(APP)], check=True)
    if sandbox:
        # 2. The app itself, with the sandbox entitlements. No --deep here: the nested code stays as signed above.
        subprocess.run(
            ["codesign", "--force", "--sign", "-", "--timestamp=none",
             "--entitlements", str(PKG / "Privatier.entitlements"), str(APP)],
            check=True,
        )
    subprocess.run(["codesign", "--verify", "--deep", "--strict", str(APP)], check=True)
    print("sandbox:", "ON (App Sandbox entitlements)" if sandbox else "OFF (debug build, not for colleagues)")
    print("app size:", size_of(APP))


def self_test() -> None:
    say("Self-test of the built app (no window opens)")
    start = time.time()
    result = subprocess.run([str(APP / "Contents" / "MacOS" / "Privatier"), "--self-test"])
    print(f"({time.time() - start:.0f} s)")
    if result.returncode != 0:
        sys.exit("The self-test of the built app FAILED. No dmg was made.")
    say("Window test of the built app (the window opens for a few seconds)")
    result = subprocess.run([str(APP / "Contents" / "MacOS" / "Privatier"), "--window-test"])
    if result.returncode != 0:
        sys.exit("The window test of the built app FAILED. No dmg was made.")


def build_dmg() -> None:
    if not APP.is_dir():
        sys.exit(f"{APP} does not exist. Build the app first (without --dmg-only).")
    say("Making the disk image")
    import dmgbuild

    out = DIST / f"Privatier-{version()}-arm64.dmg"
    out.unlink(missing_ok=True)
    try:
        dmgbuild.build_dmg(
            str(out), "Privatier", str(PKG / "dmg_settings.py"),
            defines={"app": str(APP), "settings_file": str(PKG / "dmg_settings.py")},
        )
    except Exception as exc:
        sys.exit(
            f"The disk image could not be made ({type(exc).__name__}). It needs a normal Terminal window "
            "(not a restricted or sandboxed one) because it uses macOS 'hdiutil'. The app in dist/ is fine; "
            "run again with:  sh packaging/build_app.sh --dmg-only"
        )
    print("disk image:", out, size_of(out))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--app-only", action="store_true", help="build the app, no disk image")
    parser.add_argument("--dmg-only", action="store_true", help="make only the disk image from the existing app")
    parser.add_argument("--sign-only", action="store_true",
                        help="sign the existing app again (after changing the entitlements), test it, make the dmg")
    parser.add_argument("--no-sandbox", action="store_true",
                        help="debug build without the App Sandbox (implies --app-only; do not hand it out)")
    parser.add_argument("--no-selftest", action="store_true", help="do not run the self-test after building")
    args = parser.parse_args()
    if args.dmg_only:
        build_dmg()
    else:
        if args.sign_only:
            sign(sandbox=True)
        else:
            build_app(sandbox=not args.no_sandbox)
        if not args.no_selftest:
            self_test()
        if not args.app_only and not args.no_sandbox:
            build_dmg()
    say("Done")


if __name__ == "__main__":
    main()
