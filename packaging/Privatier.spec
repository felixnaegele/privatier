# PyInstaller recipe for Privatier.app. Run through build_app.py (it prepares build/ai_stage first).
import re
from pathlib import Path

from PyInstaller.utils.hooks import collect_data_files, collect_submodules

ROOT = Path(SPECPATH).parent
SRC = ROOT / "src"
VERSION = re.search(r'__version__\s*=\s*"([^"]+)"', (SRC / "privatier" / "__init__.py").read_text()).group(1)
AI_STAGE = ROOT / "build" / "ai_stage"
assert (AI_STAGE / "hub").is_dir(), "run packaging/build_app.py (it stages the AI model first)"

# Files are taken from the source tree at build time: window.py, service.py, ui.html and the engine are not copied.
datas = [
    (str(SRC / "privatier" / "app" / "ui.html"), "privatier/app"),  # window.py reads Path(__file__).parent / "ui.html"
    (str(AI_STAGE / "hub"), "ai/hub"),
    (str(AI_STAGE / "legal"), "legal"),
]
datas += collect_data_files("gliner")

hiddenimports = collect_submodules("privatier") + collect_submodules("gliner")
hiddenimports += ["pyreadstat._readstat_parser", "pyreadstat._readstat_writer", "pyreadstat.worker"]

excludes = [
    "tkinter", "_tkinter", "turtle", "pytest", "_pytest", "IPython", "jupyter", "notebook", "matplotlib",
    "sphinx", "docutils", "tensorboard", "torchvision", "torchaudio", "torchtext", "caffe2",
    "onnx", "onnxruntime", "tensorflow", "keras", "jax", "flax", "scipy.tests", "numpy.tests",
    "pandas.tests", "reportlab", "dmgbuild", "PyInstaller",
]

a = Analysis(
    [str(ROOT / "packaging" / "entry.py")],
    pathex=[str(SRC)],
    datas=datas,
    hiddenimports=hiddenimports,
    excludes=excludes,
    noarchive=False,
)
pyz = PYZ(a.pure)
exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="Privatier",
    debug=False,
    strip=False,
    upx=False,
    console=False,  # windowed; --self-test still prints to the terminal it was started from
    argv_emulation=False,
    target_arch="arm64",
)
coll = COLLECT(exe, a.binaries, a.datas, strip=False, upx=False, name="Privatier")
app = BUNDLE(
    coll,
    name="Privatier.app",
    icon=str(ROOT / "packaging" / "icon.icns"),
    bundle_identifier="org.privatier.app",
    version=VERSION,
    info_plist={
        "CFBundleName": "Privatier",
        "CFBundleDisplayName": "Privatier",
        "CFBundleExecutable": "Privatier",
        "CFBundleShortVersionString": VERSION,
        "CFBundleVersion": VERSION,
        "CFBundlePackageType": "APPL",
        "LSMinimumSystemVersion": "14.0",  # the bundled PyTorch needs macOS 14
        "LSApplicationCategoryType": "public.app-category.productivity",
        "NSHighResolutionCapable": True,
        "NSHumanReadableCopyright": "Copyright 2026 Felix Naegele and Privatier contributors. Apache License 2.0.",
        "NSRequiresAquaSystemAppearance": False,
        "LSArchitecturePriority": ["arm64"],
    },
)
