from app.core.text import levenshtein, loose, normalize


def test_normalize():
    assert normalize("  Leverage\t Point ") == "leverage point"


def test_loose_strips_vietnamese_accents():
    assert loose("Từ bỏ!") == "tu bo"
    assert loose("Đường") == "duong"


def test_levenshtein():
    assert levenshtein("kitten", "sitting") == 3
    assert levenshtein("", "abc") == 3
