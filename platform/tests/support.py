"""platform.tests.support — reusable test fixtures for the persistence layer.

Other waves' tests import ``temp_db`` from here, so keep it clean and documented.
``temp_db()`` is a context manager that yields a ready ``sqlite3.Connection`` on a
fresh temp-FILE sqlite database (schema initialised, ``foreign_keys = ON``) and
deletes the file (plus any ``-wal`` / ``-shm`` sidecars) on exit.

Usage::

    from platform.tests.support import temp_db

    with temp_db() as conn:
        db.upsert_store(conn, id="s1", name="Acme", url="https://acme.test")
        ...
"""

from __future__ import annotations

import contextlib
import os
import sys
import tempfile

# Make ``import platform...`` resolve to this repo regardless of cwd (mirrors the
# stylist test convention). Absolute import only — see platform/__init__.py note.
_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from platform import db  # noqa: E402


@contextlib.contextmanager
def temp_db():
    """Yield a connection on a throwaway temp-file db, cleaning the file up after.

    The schema is initialised and ``PRAGMA foreign_keys`` is ON (both done by
    ``db.connect``). The connection is closed and the underlying file removed on
    exit, even if the ``with`` body raises.
    """
    fd, path = tempfile.mkstemp(suffix=".db", prefix="platform_test_")
    os.close(fd)
    conn = db.connect(path)
    try:
        yield conn
    finally:
        conn.close()
        for suffix in ("", "-wal", "-shm"):
            try:
                os.remove(path + suffix)
            except OSError:
                pass


__all__ = ["temp_db"]
