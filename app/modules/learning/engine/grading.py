"""Maps each learning mode's outcome onto a single SRS grade."""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from app.core.text import levenshtein, loose, normalize
from app.modules.learning.engine.types import Grade

FAST_ANSWER_MS = 3000


class Verdict(str, Enum):
    EXACT = "exact"
    CLOSE = "close"
    WRONG = "wrong"


@dataclass(frozen=True)
class GradeResult:
    grade: Grade
    verdict: Verdict

    @property
    def is_correct(self) -> bool:
        return self.grade != Grade.AGAIN


def grade_choice(correct: bool, confident: bool = True, response_ms: int | None = None) -> GradeResult:
    """Multiple choice: wrong -> AGAIN, guessed -> HARD, right -> GOOD, fast & sure -> EASY."""
    if not correct:
        return GradeResult(Grade.AGAIN, Verdict.WRONG)
    if not confident:
        return GradeResult(Grade.HARD, Verdict.EXACT)
    if response_ms is not None and response_ms < FAST_ANSWER_MS:
        return GradeResult(Grade.EASY, Verdict.EXACT)
    return GradeResult(Grade.GOOD, Verdict.EXACT)


def compare_answer(answer: str, expected: str) -> Verdict:
    if not answer or not answer.strip():
        return Verdict.WRONG
    if normalize(answer) == normalize(expected):
        return Verdict.EXACT
    a, e = loose(answer), loose(expected)
    if a == e:
        return Verdict.CLOSE  # only case/accents/punctuation differ
    if len(e) >= 4 and levenshtein(a, e) <= 1:
        return Verdict.CLOSE  # one-letter typo
    return Verdict.WRONG


def grade_typing(answer: str, expected: str, confident: bool = True) -> GradeResult:
    verdict = compare_answer(answer, expected)
    if verdict == Verdict.WRONG:
        return GradeResult(Grade.AGAIN, verdict)
    if verdict == Verdict.CLOSE or not confident:
        return GradeResult(Grade.HARD, verdict)
    return GradeResult(Grade.GOOD, verdict)
