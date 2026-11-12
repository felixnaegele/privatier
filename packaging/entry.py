"""Start file of the installed Privatier.app (PyInstaller runs this).

Normal start:  opens the window.
Hidden flag:   Privatier --self-test   runs the self-test without a window and exits with 0 (passed) or 1 (failed).
Hidden flag:   Privatier --window-test opens the window for a few seconds and checks that the page is shown.
"""

import multiprocessing
import os
import sys


def _no_network() -> None:
    """The app never uses the network. macOS needs the app to hold the network permission, or the window stays blank
    (its page is drawn by WebKit, which refuses to start without it). So the app itself refuses every connection."""
    import errno
    import socket

    def refused(*args, **kwargs):
        raise PermissionError(errno.EPERM, "Privatier does not use the network.")

    socket.socket.connect = refused
    socket.socket.connect_ex = refused
    socket.create_connection = refused
    socket.getaddrinfo = refused


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
        # The sandbox refuses the system lists of file types (/etc/apache2/mime.types), and the Excel library
        # fails on that refusal. Python's built-in list is enough: do not look outside the app.
        import mimetypes

        mimetypes.knownfiles = []
        os.environ.setdefault("TOKENIZERS_PARALLELISM", "false")
        _no_network()
        os.environ.setdefault("PYTORCH_ENABLE_MPS_FALLBACK", "1")
        if sys.stdout is None:  # started from Finder: no terminal attached
            sys.stdout = sys.stderr = open(os.devnull, "w")
    if "--self-test" in sys.argv[1:]:
        from privatier.app import selftest

        sys.exit(selftest.run())
    from privatier.app import window

    if "--window-test" in sys.argv[1:]:
        sys.exit(window.window_test())
    window.main()


if __name__ == "__main__":
    main()
