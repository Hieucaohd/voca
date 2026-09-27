"""Custom `flask voca ...` commands."""
from __future__ import annotations

import click
from flask import Flask
from sqlalchemy import select

from app.extensions import db

LANGUAGES = [
    ("en", "English", "English", False),
    ("vi", "Vietnamese", "Tiếng Việt", False),
    ("ja", "Japanese", "日本語", False),
    ("ko", "Korean", "한국어", False),
    ("zh", "Chinese", "中文", False),
    ("fr", "French", "Français", False),
    ("de", "German", "Deutsch", False),
    ("es", "Spanish", "Español", False),
]


def seed_languages() -> int:
    from app.modules.vocabulary.models import Language

    existing = set(db.session.scalars(select(Language.code)))
    added = 0
    for code, name, native, rtl in LANGUAGES:
        if code not in existing:
            db.session.add(Language(code=code, name=name, native_name=native, is_rtl=rtl))
            added += 1
    db.session.commit()
    return added


def register_cli(app: Flask) -> None:
    @app.cli.group("voca")
    def voca():
        """Voca maintenance commands."""

    @voca.command("seed")
    def seed():
        """Insert reference data (languages). Safe to run repeatedly."""
        click.echo(f"Added {seed_languages()} languages")

    @voca.command("create-db")
    def create_db():
        """Create all tables without migrations (quick local start) and seed."""
        db.create_all()
        click.echo(f"Tables created, added {seed_languages()} languages")
