"""Runs a full user flow through the libSQL driver (the Turso code path) on a local file."""
import pytest
from sqlalchemy.pool import NullPool

from app import create_app
from app.cli import seed_languages
from app.extensions import db
from tests.conftest import Api


@pytest.fixture()
def libsql_client(tmp_path):
    app = create_app(
        "testing",
        overrides={
            "SQLALCHEMY_DATABASE_URI": f"sqlite+libsql:///{(tmp_path / 'voca.db').as_posix()}",
            "SQLALCHEMY_ENGINE_OPTIONS": {"poolclass": NullPool},
        },
    )
    with app.app_context():
        assert db.engine.dialect.driver == "libsql"
        db.create_all()
        seed_languages()
        yield app.test_client()
        db.session.remove()
        db.engine.dispose()


def test_full_flow_on_libsql(libsql_client):
    alice = Api(libsql_client, "alice@example.com")
    word = alice.add_word("leverage", "đòn bẩy", tags=["Finance"], contexts=[{"sentence": "Banks leverage capital.", "source_title": "Quant"}])
    assert alice.post("/api/v1/words", {"word": "Leverage"}).status_code == 409  # IntegrityError path via dedup check

    queue = alice.get("/api/v1/reviews/today").get_json()["items"]
    assert [i["word"] for i in queue] == ["leverage"]
    result = alice.post(f"/api/v1/reviews/{word['id']}/result", {"mode": "flashcard", "grade": "good"}).get_json()
    assert result["progress"]["interval_days"] == 1
    assert alice.get("/api/v1/stats/today").get_json()["completed"] == 1
    assert alice.get("/api/v1/words?q=đòn").get_json()["total"] == 1
    assert alice.delete(f"/api/v1/words/{word['id']}").status_code == 204
