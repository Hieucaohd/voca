"""Question builders for multiple-choice and typing modes."""
from __future__ import annotations

import random

from app.core.text import normalize
from app.modules.vocabulary.models import Vocabulary

MCQ_OPTIONS = 4


def _pos(vocab: Vocabulary) -> str | None:
    return vocab.senses[0].part_of_speech if vocab.senses else None


def build_mcq(target: Vocabulary, pool: list[Vocabulary], rng: random.Random) -> dict:
    """word -> choose its meaning. Distractors prefer the same part of speech."""
    answer = target.primary_meaning
    seen = {normalize(answer)}
    candidates = [v for v in pool if v.id != target.id and v.language_code == target.language_code and v.primary_meaning]
    rng.shuffle(candidates)
    candidates.sort(key=lambda v: _pos(v) != _pos(target))  # stable: same POS first, random within

    options = [answer]
    for vocab in candidates:
        meaning = vocab.primary_meaning
        if normalize(meaning) not in seen:
            seen.add(normalize(meaning))
            options.append(meaning)
        if len(options) == MCQ_OPTIONS:
            break
    rng.shuffle(options)
    return {"type": "mcq", "prompt": target.text, "options": options}


def build_typing(target: Vocabulary) -> dict:
    """meaning -> type the word. The first letter and length are given as a hint."""
    sense = target.senses[0] if target.senses else None
    return {
        "type": "typing",
        "prompt": target.primary_meaning,
        "part_of_speech": sense.part_of_speech if sense else None,
        "hint": f"{target.text[0]}{'_' * (len(target.text) - 1)}" if target.text else "",
    }
