from datetime import timedelta

from app.core.clock import utcnow
from app.extensions import db
from app.modules.learning.models import CardProgress, StudyPlan


def _deck(api, name="Deck", words=(), **extra):
    deck = api.post("/api/v1/collections", {"name": name, **extra}).get_json()
    for w in words:
        api.add_word(w, collection_ids=[deck["id"]])
    return deck


def _queue_words(api, collection_id=None):
    url = "/api/v1/reviews/today" + (f"?collection_id={collection_id}" if collection_id else "")
    res = api.get(url)
    assert res.status_code == 200, res.get_json()
    return [i["word"] for i in res.get_json()["items"]]


def _calendar(api, days=5, collection_id=None):
    url = f"/api/v1/study/calendar?days={days}" + (f"&collection_id={collection_id}" if collection_id else "")
    return api.get(url).get_json()["days"]


def _learn(api, words, grade="good"):
    ids = {i["word"]: i["id"] for i in api.get("/api/v1/reviews/today").get_json()["items"]}
    for w in words:
        assert api.post(f"/api/v1/reviews/{ids[w]}/result", {"mode": "flashcard", "grade": grade}).status_code == 200


def test_words_are_not_scheduled_until_the_collection_is_started(alice):
    deck = _deck(alice, words=["alpha", "beta"])
    assert _queue_words(alice) == []
    assert alice.get("/api/v1/reviews/summary").get_json()["started"] is False
    assert alice.get(f"/api/v1/reviews/summary?collection_id={deck['id']}").get_json()["started"] is False
    assert all(not d["collections"] for d in _calendar(alice))

    res = alice.get(f"/api/v1/reviews/today?collection_id={deck['id']}")
    assert res.status_code == 409
    assert res.get_json()["error"]["details"]["reason"] == "NOT_STARTED"

    plan = alice.start(deck["id"], new_per_day=5)
    assert (plan["status"], plan["total_words"], plan["new_today"]) == ("active", 2, 2)
    assert _queue_words(alice, deck["id"]) == ["alpha", "beta"]


def test_start_spreads_new_words_over_days_in_added_order(alice):
    deck = _deck(alice, words=["w1", "w2", "w3", "w4", "w5"])
    plan = alice.start(deck["id"], new_per_day=2)
    assert plan["days_to_finish_new"] == 3

    days = _calendar(alice, days=4)
    assert days[0]["is_today"] is True
    assert [[w["word"] for g in d["collections"] for w in g["new"]] for d in days] == [["w1", "w2"], ["w3", "w4"], ["w5"], []]
    assert days[0]["collections"][0]["collection_name"] == "Deck"


def test_learning_today_empties_the_collection_queue(alice):
    deck = _deck(alice, words=["w1", "w2", "w3"])
    alice.start(deck["id"], new_per_day=2)
    _learn(alice, ["w1", "w2"])

    assert _queue_words(alice, deck["id"]) == []  # nothing more today: w3 is tomorrow's
    summary = alice.get(f"/api/v1/reviews/summary?collection_id={deck['id']}").get_json()
    assert (summary["due"], summary["new_today"], summary["todo"]) == (0, 0, 0)
    plan = alice.get(f"/api/v1/collections/{deck['id']}/study").get_json()
    assert (plan["learned_today"], plan["started_words"], plan["todo_today"]) == (2, 2, 0)

    tomorrow = _calendar(alice, days=2)[1]["collections"][0]
    assert sorted(w["word"] for w in tomorrow["reviews"]) == ["w1", "w2"]
    assert [w["word"] for w in tomorrow["new"]] == ["w3"]


def test_forgotten_words_come_back_today(alice):
    deck = _deck(alice, words=["w1"])
    alice.start(deck["id"])
    _learn(alice, ["w1"], grade="again")
    assert _queue_words(alice, deck["id"]) == ["w1"]
    assert [w["word"] for w in _calendar(alice, 1)[0]["collections"][0]["reviews"]] == ["w1"]


def test_missed_days_do_not_pile_up_new_words(alice):
    deck = _deck(alice, words=[f"w{i}" for i in range(10)])
    alice.start(deck["id"], new_per_day=2)
    plan = db.session.query(StudyPlan).one()
    plan.started_at = utcnow() - timedelta(days=5)  # started long ago, never studied
    db.session.commit()
    assert _queue_words(alice, deck["id"]) == ["w0", "w1"]


def test_yesterdays_learning_does_not_use_todays_slots(alice):
    deck = _deck(alice, words=["w1", "w2", "w3"])
    alice.start(deck["id"], new_per_day=1)
    _learn(alice, ["w1"])
    for progress in db.session.query(CardProgress):
        progress.first_reviewed_at = utcnow() - timedelta(days=1)
        progress.due_at = utcnow() + timedelta(days=1)
    db.session.commit()
    assert _queue_words(alice, deck["id"]) == ["w2"]


def test_words_added_later_join_the_end(alice):
    deck = _deck(alice, words=["w1", "w2"])
    alice.start(deck["id"], new_per_day=1)
    alice.add_word("late", collection_ids=[deck["id"]])
    new_by_day = [[w["word"] for g in d["collections"] for w in g["new"]] for d in _calendar(alice, days=3)]
    assert new_by_day == [["w1"], ["w2"], ["late"]]


def test_pause_resume_and_change_pace(alice):
    deck = _deck(alice, words=["w1", "w2", "w3"])
    alice.start(deck["id"], new_per_day=1)
    assert alice.patch(f"/api/v1/collections/{deck['id']}/study", {"status": "paused"}).get_json()["status"] == "paused"
    assert _queue_words(alice) == []
    assert alice.get(f"/api/v1/reviews/today?collection_id={deck['id']}").status_code == 409

    alice.patch(f"/api/v1/collections/{deck['id']}/study", {"status": "active", "new_per_day": 3})
    assert _queue_words(alice, deck["id"]) == ["w1", "w2", "w3"]

    assert alice.patch(f"/api/v1/collections/{deck['id']}/study", {"new_per_day": 500}).status_code == 422
    assert alice.delete(f"/api/v1/collections/{deck['id']}/study").status_code == 204
    assert alice.patch(f"/api/v1/collections/{deck['id']}/study", {"new_per_day": 2}).status_code == 404


def test_new_per_day_zero_means_reviews_only(alice):
    deck = _deck(alice, words=["w1", "w2"])
    alice.start(deck["id"], new_per_day=1)
    _learn(alice, ["w1"], grade="again")
    alice.patch(f"/api/v1/collections/{deck['id']}/study", {"new_per_day": 0})
    assert _queue_words(alice, deck["id"]) == ["w1"]


def test_word_in_two_started_collections_is_introduced_once(alice):
    a = _deck(alice, "A", words=["shared"])
    b = _deck(alice, "B")
    alice.post(f"/api/v1/collections/{b['id']}/words", {"vocabulary_ids": [alice.get("/api/v1/words?q=shared").get_json()["items"][0]["id"]]})
    alice.add_word("only-b", collection_ids=[b["id"]])
    alice.start(a["id"])
    alice.start(b["id"])

    assert _queue_words(alice) == ["shared", "only-b"]
    today = _calendar(alice, 1)[0]
    assert sorted(w["word"] for g in today["collections"] for w in g["new"]) == ["only-b", "shared"]
    # Each collection's own view still lists it.
    assert _queue_words(alice, b["id"]) == ["shared", "only-b"]


def test_manual_words_default_to_inbox(alice):
    word = alice.add_word("loose")
    assert [c["name"] for c in alice.get(f"/api/v1/words/{word['id']}").get_json()["collections"]] == ["Hộp thư từ mới"]


def test_plans_listing_and_stats_follow_active_plans(alice):
    deck = _deck(alice, words=["w1", "w2"])
    _deck(alice, "Other", words=["x1"])
    alice.start(deck["id"], new_per_day=1)
    plans = alice.get("/api/v1/study/plans").get_json()["items"]
    assert [(p["collection"]["name"], p["new_today"], p["unseen_words"]) for p in plans] == [("Deck", 1, 2)]
    overview = alice.get("/api/v1/stats/overview").get_json()
    assert overview["learning_pool"] == 2  # "Other" is not started
    assert alice.get("/api/v1/stats/today").get_json()["new_available"] == 1


def test_study_web_pages(client, alice):
    client.post("/login", data={"email": "alice@example.com", "password": "password123"})
    deck = _deck(alice, words=["w1", "w2"])
    page = client.get(f"/collections/{deck['id']}").get_data(as_text=True)
    assert "Bắt đầu học" in page
    assert "chưa được bắt đầu học" in client.get(f"/learn?collection_id={deck['id']}").get_data(as_text=True)
    assert client.get(f"/schedule?collection_id={deck['id']}").status_code == 302
    assert "Chưa có lịch học" in client.get("/schedule").get_data(as_text=True)

    alice.start(deck["id"], new_per_day=1)
    page = client.get(f"/collections/{deck['id']}").get_data(as_text=True)
    assert "Học hôm nay (1)" in page
    schedule = client.get(f"/schedule?collection_id={deck['id']}&days=7").get_data(as_text=True)
    assert "Hôm nay" in schedule and "w1" in schedule and "w2" in schedule
    assert "Học (1)" in client.get("/collections").get_data(as_text=True)
    assert "Deck" in client.get("/dashboard").get_data(as_text=True)

    _learn(alice, ["w1"])
    assert "Đã học xong hôm nay" in client.get(f"/collections/{deck['id']}").get_data(as_text=True)
    assert "Hôm nay đã học xong" in client.get(f"/learn?collection_id={deck['id']}").get_data(as_text=True)
