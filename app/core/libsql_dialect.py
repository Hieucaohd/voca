"""SQLAlchemy dialect ``sqlite+libsql`` backed by :mod:`app.core.libsql_dbapi`.

URL forms:
    sqlite+libsql://<db>-<org>.turso.io?secure=true   -> remote Turso (libsql://)
    sqlite+libsql://127.0.0.1:8080                     -> local ``turso dev`` (http://)
    sqlite+libsql:///path/to/file.db                   -> local file via libsql

The auth token is passed through ``connect_args={"auth_token": ...}``.
"""
from __future__ import annotations

import os

from sqlalchemy.dialects import registry
from sqlalchemy.dialects.sqlite.pysqlite import SQLiteDialect_pysqlite


class SQLiteDialect_libsql(SQLiteDialect_pysqlite):
    driver = "libsql"
    supports_statement_cache = True

    @classmethod
    def import_dbapi(cls):
        from app.core import libsql_dbapi

        return libsql_dbapi

    def on_connect(self):
        # pysqlite's hook registers Python functions (REGEXP), which libsql
        # connections do not support.
        return None

    def create_connect_args(self, url):
        opts = dict(url.query)
        secure = str(opts.pop("secure", "true")).lower() in {"1", "true", "yes"}
        if url.host:
            if secure:
                database = f"libsql://{url.host}"
            else:
                port = f":{url.port}" if url.port else ""
                database = f"http://{url.host}{port}"
        else:
            database = url.database or ":memory:"
            if database != ":memory:":
                database = os.path.abspath(database)
        return [database], {"_check_same_thread": False}

    def get_isolation_level(self, dbapi_connection):
        # SQLite transactions are always serializable; avoid a PRAGMA round trip
        # that remote libSQL servers are not guaranteed to support.
        return "SERIALIZABLE"

    def set_isolation_level(self, dbapi_connection, level):
        if level not in ("SERIALIZABLE", "AUTOCOMMIT"):
            raise NotImplementedError(f"libSQL does not support isolation level {level}")

    def is_disconnect(self, e, connection, cursor):
        message = str(e).lower()
        return "stream" in message and ("expired" in message or "closed" in message)


def register() -> None:
    registry.register("sqlite.libsql", __name__, "SQLiteDialect_libsql")


dialect = SQLiteDialect_libsql
