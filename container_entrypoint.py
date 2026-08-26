from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path


def main() -> None:
    if hasattr(os, "getuid") and os.getuid() == 0:
        raise RuntimeError("PP darf im Container nicht als root laufen")
    # Neue Datenbank-, WAL- und Token-Dateien werden nur für den Containerbenutzer lesbar.
    os.umask(0o077)
    data = Path(os.getenv("PP_DATA_DIR", "/app/data"))
    data.mkdir(parents=True, exist_ok=True)
    try:
        data.chmod(0o700)
    except OSError:
        pass
    with tempfile.NamedTemporaryFile(prefix=".pp-write-test-", dir=data):
        pass
    os.execv(sys.executable, [sys.executable, "-m", "pp.server"])


if __name__ == "__main__":
    main()
