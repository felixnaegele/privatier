"""Start file of the installed Privatier.app (PyInstaller runs this).

Normal start:  opens the window.
Hidden flag:   Privatier --self-test   runs the self-test without a window and exits with 0 (passed) or 1 (failed).
"""

import multiprocessing
import os
import sys


def main() -> None:
    multiprocessing.freeze_support()  # a helper process of the AI libraries must not open a second window
    if getattr(sys, "frozen", False):
        # The AI model lives inside the app: read it from there and never use the internet.
        base = getattr(sys, "_MEIPASS", os.path.dirname(sys.executable))
        hub = os.path.join(base, "ai", "hub")
        os.environ["HF_HUB_CACHE"] = hub
        os.environ["HUGGINGFACE_HUB_CACHE"] = hub
        os.environ["HF_HUB_OFFLINE"] = "1"
        os.environ["TRANSFORMERS_OFFLINE"] = "1"
        os.environ.setdefault("TOKENIZERS_PARALLELISM", "false")
        os.environ.setdefault("PYTORCH_ENABLE_MPS_FALLBACK", "1")
        if sys.stdout is None:  # started from Finder: no terminal attached
            sys.stdout = sys.stderr = open(os.devnull, "w")
    if "--self-test" in sys.argv[1:]:
        from privatier.app import selftest

        sys.exit(selftest.run())
    from privatier.app import window

    window.main()


if __name__ == "__main__":
    main()
