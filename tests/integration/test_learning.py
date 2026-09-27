from datetime import date, datetime, timedelta, timezone

from app.extensions import db
from app.modules.learning.models import CardProgress, DailyActivity
from app.modules.stats.service import streaks


def _queue(api, mode="flashcard", **params):
    query = "&".join(f"{k}={v}" for k, v in {"mode": mode, **params}.items())
    res = api.get(f"/api/v1/reviews/today?{query}")
    assert res.status_code == 200, res.get_json()
    return res.get_json()


def test_new_words_respect_daily_limit(alice):
    alice.patch("/api/v1/me", {"daily_new_limit": 2})
    for w in ("one", "two", "three"):
        alice.add_word(w)
    body = _queue(alice)
    assert [i["word"] for i in body["items"]] == ["one", "two"]
    assert all(i["kind"] == "new" for i in body["items"])
    assert body["items"][0]["preview"] == {"again": "10 phút", "hard": "1 ngày", "good": "1 ngày", "easy": "3 ngày"}

    for item in body["items"]:
        alice.post(f"/api/v1/reviews/{item['id']}/result", {"mode": "flashcard", "grade": "good"})
    assert _queue(alice)["items"] == []  # limit used up; learned cards are due tomorrow
    assert _queue(alice)["summary"]["new_available"] == 1


def test_flashcard_review_updates_progress_and_activity(alice):
    word = alice.add_word("abandon", "từ bỏ")
    res = alice.post(f"/api/v1/reviews/{word['id']}/result", {"mode": "flashcard", "grade": "good", "response_ms": 4200})
    body = res.get_json()
    assert body["progress"]["status"] == "LEARNING"
    assert body["progress"]["interval_days"] == 1
    assert body["next_review_in"] == "1 ngày"

    progress = db.session.query(CardProgress).one()
    assert (progress.review_count, progress.correct_count) == (1, 1)
    activity = db.session.query(DailyActivity).one()
    assert (activity.reviews, activity.correct, activity.new_learned, activity.time_spent_ms) == (1, 1, 1, 4200)


def test_again_is_due_again_today(alice):
    word = alice.add_word("forget")
    body = alice.post(f"/api/v1/reviews/{word['id']}/result", {"mode": "flashcard", "grade": "again"}).get_json()
    assert body["is_correct"] is False
    assert body["progress"]["status"] == "LEARNING"
    items = _queue(alice)["items"]
    assert [(i["word"], i["kind"]) for i in items] == [("forget", "review")]


def test_mcq_is_graded_by_server(alice):
    target = alice.add_word("leverage", "đòn bẩy")
    for w, m in [("hedge", "phòng hộ"), ("yield", "lợi suất"), ("spread", "chênh lệch"), ("asset", "tài sản")]:
        alice.add_word(w, m)
    items = _queue(alice, "mcq")["items"]
    quiz = next(i for i in items if i["id"] == target["id"])["quiz"]
    assert quiz["prompt"] == "leverage"
    assert len(quiz["options"]) == 4 and "đòn bẩy" in quiz["options"]

    wrong = alice.post(f"/api/v1/reviews/{target['id']}/result", {"mode": "mcq", "answer": "tài sản"}).get_json()
    assert (wrong["grade"], wrong["correct_answer"]) == ("again", "đòn bẩy")
    right = alice.post(f"/api/v1/reviews/{target['id']}/result", {"mode": "mcq", "answer": "đòn bẩy", "confident": False}).get_json()
    assert right["grade"] == "hard"


def test_typing_grades_typos_as_hard(alice):
    word = alice.add_word("abandon", "từ bỏ")
    quiz = _queue(alice, "typing")["items"][0]["quiz"]
    assert quiz == {"type": "typing", "prompt": "từ bỏ", "part_of_speech": "noun", "hint": "a______"}
    body = alice.post(f"/api/v1/reviews/{word['id']}/result", {"mode": "typing", "answer": "abandn"}).get_json()
    assert (body["grade"], body["verdict"], body["correct_answer"]) == ("hard", "close", "abandon")


def test_review_validation(alice):
    word = alice.add_word("x-ray")
    assert alice.post(f"/api/v1/reviews/{word['id']}/result", {"mode": "flashcard"}).status_code == 422
    assert alice.post(f"/api/v1/reviews/{word['id']}/result", {"mode": "flashcard", "grade": "great"}).status_code == 422
    assert alice.post(f"/api/v1/reviews/{word['id']}/result", {"mode": "typing"}).status_code == 422


def test_client_review_id_is_idempotent(alice):
    word = alice.add_word("retry")
    payload = {"mode": "flashcard", "grade": "good", "client_review_id": "abc-123"}
    first = alice.post(f"/api/v1/reviews/{word['id']}/result", payload).get_json()
    second = alice.post(f"/api/v1/reviews/{word['id']}/result", payload).get_json()
    assert first["progress"] == second["progress"]
    assert db.session.query(CardProgress).one().review_count == 1


def test_suspend_known_reset(alice):
    a = alice.add_word("alpha")
    b = alice.add_word("beta")
    assert alice.post(f"/api/v1/words/{a['id']}/suspend").get_json()["status"] == "SUSPENDED"
    assert [i["word"] for i in _queue(alice)["items"]] == ["beta"]
    assert alice.post(f"/api/v1/reviews/{a['id']}/result", {"mode": "flashcard", "grade": "good"}).status_code == 409
    assert alice.post(f"/api/v1/words/{a['id']}/unsuspend").get_json()["status"] == "NEW"

    known = alice.post(f"/api/v1/words/{b['id']}/known").get_json()
    assert (known["status"], known["interval_days"]) == ("MASTERED", 30)
    assert alice.post(f"/api/v1/words/{b['id']}/reset").get_json()["status"] == "NEW"
    assert sorted(i["word"] for i in _queue(alice)["items"]) == ["alpha", "beta"]


def test_other_users_cannot_review_private_words(alice, bob):
    word = alice.add_word("mine")
    assert bob.post(f"/api/v1/reviews/{word['id']}/result", {"mode": "flashcard", "grade": "good"}).status_code == 404


def test_stats_today_and_overview(alice):
    words = [alice.add_word(w) for w in ("a1", "b2", "c3")]
    alice.post(f"/api/v1/reviews/{words[0]['id']}/result", {"mode": "flashcard", "grade": "good"})
    alice.post(f"/api/v1/reviews/{words[1]['id']}/result", {"mode": "flashcard", "grade": "again"})
    alice.post(f"/api/v1/words/{words[2]['id']}/known")

    today = alice.get("/api/v1/stats/today").get_json()
    assert (today["completed"], today["reviews"], today["accuracy"]) == (2, 2, 50)
    overview = alice.get("/api/v1/stats/overview").get_json()
    assert overview["status_counts"]["LEARNING"] == 2
    assert overview["mastered"] == 1
    assert overview["streak"]["current"] == 1
    assert len(alice.get("/api/v1/stats/calendar").get_json()["items"]) == 1


def test_streaks():
    today = date(2026, 9, 28)
    days = {today - timedelta(days=n) for n in (1, 2, 3, 7, 8)}
    assert streaks(days, today) == (3, 3)  # today not studied yet: streak still alive
    assert streaks(days | {today}, today) == (4, 4)
    assert streaks({today - timedelta(days=2)}, today) == (0, 1)
    assert streaks(set(), today) == (0, 0)


def test_due_uses_learner_timezone(alice):
    """A card due at local midnight must be in 'today' for the learner, whatever UTC says."""
    word = alice.add_word("midnight")
    alice.post(f"/api/v1/reviews/{word['id']}/result", {"mode": "flashcard", "grade": "good"})
    progress = db.session.query(CardProgress).one()
    progress.due_at = datetime.now(timezone.utc) - timedelta(minutes=1)
    db.session.commit()
    assert [i["word"] for i in _queue(alice)["items"]] == ["midnight"]
