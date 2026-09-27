"""PEP 249 adapter around the ``libsql`` driver (Turso).

The native ``libsql`` module speaks a sqlite3-like API but raises bare
``ValueError`` for every database failure and lacks the DB-API exception
hierarchy. SQLAlchemy relies on that hierarchy to wrap errors (e.g.
``IntegrityError``), so this module provides it and translates errors.
"""
from __future__ import annotations

from typing import Any

import libsql as _libsql

apilevel = "2.0"
threadsafety = 1
paramstyle = "qmark"
sqlite_version_info = _libsql.sqlite_version_info
sqlite_version = ".".join(str(p) for p in sqlite_version_info)


class Warning(Exception):  # noqa: A001 - name mandated by PEP 249
    pass


class Error(Exception):
    pass


class InterfaceError(Error):
    pass


class DatabaseError(Error):
    pass


class DataError(DatabaseError):
    pass


class OperationalError(DatabaseError):
    pass


class IntegrityError(DatabaseError):
    pass


class InternalError(DatabaseError):
    pass


class ProgrammingError(DatabaseError):
    pass


class NotSupportedError(DatabaseError):
    pass


def _translate(exc: Exception) -> Error:
    message = str(exc)
    lowered = message.lower()
    if "constraint failed" in lowered:
        return IntegrityError(message)
    if "syntax error" in lowered or "no such" in lowered:
        return ProgrammingError(message)
    return OperationalError(message)


def _call(fn, *args, **kwargs):
    try:
        return fn(*args, **kwargs)
    except Error:
        raise
    except (ValueError, RuntimeError) as exc:
        raise _translate(exc) from exc


class Cursor:
    def __init__(self, raw) -> None:
        self._raw = raw

    def execute(self, sql: str, parameters: Any = ()):
        _call(self._raw.execute, sql, tuple(parameters or ()))
        return self

    def executemany(self, sql: str, seq_of_parameters):
        _call(self._raw.executemany, sql, [tuple(p) for p in seq_of_parameters])
        return self

    def fetchone(self):
        return _call(self._raw.fetchone)

    def fetchmany(self, size: int | None = None):
        if size is None:
            return _call(self._raw.fetchmany)
        return _call(self._raw.fetchmany, size)

    def fetchall(self):
        return _call(self._raw.fetchall)

    def close(self) -> None:
        _call(self._raw.close)

    @property
    def description(self):
        desc = self._raw.description
        # libsql returns () for statements without a result set; DB-API wants None.
        return desc or None

    @property
    def rowcount(self) -> int:
        return self._raw.rowcount

    @property
    def lastrowid(self):
        return self._raw.lastrowid

    @property
    def arraysize(self) -> int:
        return self._raw.arraysize

    @arraysize.setter
    def arraysize(self, value: int) -> None:
        self._raw.arraysize = value


class Connection:
    def __init__(self, raw) -> None:
        self._raw = raw

    def cursor(self) -> Cursor:
        return Cursor(_call(self._raw.cursor))

    def commit(self) -> None:
        _call(self._raw.commit)

    def rollback(self) -> None:
        _call(self._raw.rollback)

    def close(self) -> None:
        _call(self._raw.close)

    def execute(self, sql: str, parameters: Any = ()):
        return self.cursor().execute(sql, parameters)

    @property
    def in_transaction(self) -> bool:
        return bool(self._raw.in_transaction)

    @property
    def isolation_level(self):
        return self._raw.isolation_level


def connect(database: str, **kwargs) -> Connection:
    return Connection(_call(_libsql.connect, database, **kwargs))
