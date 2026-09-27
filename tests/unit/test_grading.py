import pytest

from app.modules.learning.engine import Grade, Verdict, grade_choice, grade_typing


@pytest.mark.parametrize(
    "answer,expected,grade,verdict",
    [
        ("abandon", "abandon", Grade.GOOD, Verdict.EXACT),
        ("  Abandon ", "abandon", Grade.GOOD, Verdict.EXACT),
        ("abandn", "abandon", Grade.HARD, Verdict.CLOSE),
        ("tu bo", "từ bỏ", Grade.HARD, Verdict.CLOSE),
        ("leave", "abandon", Grade.AGAIN, Verdict.WRONG),
        ("", "abandon", Grade.AGAIN, Verdict.WRONG),
        ("cat", "car", Grade.AGAIN, Verdict.WRONG),  # short words need an exact match
    ],
)
def test_grade_typing(answer, expected, grade, verdict):
    result = grade_typing(answer, expected)
    assert (result.grade, result.verdict) == (grade, verdict)


def test_typing_not_confident_is_hard():
    assert grade_typing("abandon", "abandon", confident=False).grade == Grade.HARD


def test_grade_choice():
    assert grade_choice(False).grade == Grade.AGAIN
    assert grade_choice(True, confident=False).grade == Grade.HARD
    assert grade_choice(True, response_ms=8000).grade == Grade.GOOD
    assert grade_choice(True, response_ms=1500).grade == Grade.EASY
    assert grade_choice(True).is_correct
