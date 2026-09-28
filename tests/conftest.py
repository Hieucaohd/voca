from __future__ import annotations

import pytest

from app import create_app
from app.cli import seed_languages
from app.extensions import db


@pytest.fixture()
def app():
    app = create_app("testing")
    with app.app_context():
        db.create_all()
        seed_languages()
        yield app
        db.session.remove()
        db.drop_all()


@pytest.fixture()
def client(app):
    return app.test_client()


class Api:
    """Bearer-token API client bound to one registered user."""

    def __init__(self, client, email: str, name: str = "Tester", password: str = "password123"):
        self.client = client
        res = client.post("/api/v1/auth/register", json={"email": email, "password": password, "display_name": name})
        assert res.status_code == 201, res.get_json()
        body = res.get_json()
        self.user = body["user"]
        self.token = body["access_token"]
        self.refresh_token = body["refresh_token"]

    @property
    def headers(self):
        return {"Authorization": f"Bearer {self.token}"}

    def get(self, url, **kw):
        return self.client.get(url, headers=self.headers, **kw)

    def post(self, url, json=None, **kw):
        return self.client.post(url, json=json if json is not None else {}, headers=self.headers, **kw)

    def put(self, url, json, **kw):
        return self.client.put(url, json=json, headers=self.headers, **kw)

    def patch(self, url, json, **kw):
        return self.client.patch(url, json=json, headers=self.headers, **kw)

    def delete(self, url, **kw):
        return self.client.delete(url, headers=self.headers, **kw)

    @property
    def inbox_id(self) -> str:
        items = self.get("/api/v1/collections").get_json()["items"]
        return next(c["id"] for c in items if c["system_key"] == "inbox")

    def start(self, collection_id: str | None = None, new_per_day: int | None = None) -> dict:
        """Starts studying a collection (the Inbox by default)."""
        body = {} if new_per_day is None else {"new_per_day": new_per_day}
        res = self.post(f"/api/v1/collections/{collection_id or self.inbox_id}/study", body)
        assert res.status_code == 201, res.get_json()
        return res.get_json()

    def add_word(self, word: str, translation: str = "nghĩa", **extra) -> dict:
        payload = {"word": word, "senses": [{"translation": translation, "part_of_speech": "noun"}], **extra}
        res = self.post("/api/v1/words", payload)
        assert res.status_code == 201, res.get_json()
        return res.get_json()


@pytest.fixture()
def alice(client):
    return Api(client, "alice@example.com", "Alice")


@pytest.fixture()
def bob(client):
    return Api(client, "bob@example.com", "Bob")
