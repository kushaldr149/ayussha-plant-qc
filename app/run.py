"""Start the app (used by windows\\start.bat).

Everything shown in the start window is also written to data/logs/start.log, so a startup
error can be read later even after the window is closed.
"""
from __future__ import annotations

import datetime
import os
import socket
import sys
import traceback
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
LOG_DIR = Path(os.environ.get("DATA_DIR") or ROOT / "data") / "logs"
LOG_FILE = LOG_DIR / "start.log"
KEEP_BYTES = 2_000_000


class _Tee:
    """Write to the console and to the log file."""

    def __init__(self, stream, log):
        self._stream = stream
        self._log = log

    def write(self, text):
        try:
            self._stream.write(text)
        except (UnicodeEncodeError, ValueError):
            self._stream.write(text.encode("ascii", "replace").decode("ascii"))
        try:
            self._log.write(text)
            self._log.flush()
        except (OSError, ValueError):
            pass
        return len(text)

    def flush(self):
        for s in (self._stream, self._log):
            try:
                s.flush()
            except (OSError, ValueError):
                pass

    def isatty(self):
        return False

    def __getattr__(self, name):
        return getattr(self._stream, name)


def _open_log():
    try:
        LOG_DIR.mkdir(parents=True, exist_ok=True)
        if LOG_FILE.exists() and LOG_FILE.stat().st_size > KEEP_BYTES:
            LOG_FILE.replace(LOG_DIR / "start.old.log")
        return open(LOG_FILE, "a", encoding="utf-8")
    except OSError as e:
        print(f"Could not open the log file {LOG_FILE}: {e}")
        return None


def _port_problem(host: str, port: int) -> str | None:
    """Return a plain-language message if the address cannot be used, else None."""
    family = socket.AF_INET6 if ":" in host else socket.AF_INET
    s = socket.socket(family, socket.SOCK_STREAM)
    try:
        s.bind((host, port))
    except OSError as e:
        return (f"Port {port} on {host} cannot be used ({e}).\n"
                f"Another program may be using it, or the app may already be running in another window.\n"
                f"Close the other window, or set a different PORT in the .env file (for example PORT=8080), "
                f"then start again.")
    finally:
        s.close()
    return None


def main() -> int:
    log = _open_log()
    if log:
        sys.stdout = _Tee(sys.stdout, log)
        sys.stderr = _Tee(sys.stderr, log)
    print(f"--- start {datetime.datetime.now().isoformat(timespec='seconds')} · Python {sys.version.split()[0]} "
          f"· folder {ROOT}")
    host = os.environ.get("HOST") or "127.0.0.1"
    try:
        port = int(os.environ.get("PORT") or "8000")
    except ValueError:
        print(f"PORT in the .env file must be a number; it is '{os.environ.get('PORT')}'.")
        return 1
    problem = _port_problem(host, port)
    if problem:
        print(problem)
        return 1
    try:
        os.chdir(ROOT)
        import uvicorn
        from app.main import app  # import here so an error in the app is written to the log
        uvicorn.run(app, host=host, port=port, use_colors=False)
    except SystemExit as e:
        if e.code not in (0, None):
            print(f"The app stopped: {e.code}")
            return 1
    except KeyboardInterrupt:
        pass
    except BaseException:
        print("The app could not start. Details:")
        traceback.print_exc()
        print(f"These details are also saved in {LOG_FILE}")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
