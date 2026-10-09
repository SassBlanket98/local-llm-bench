import pytest

from llmbench.ifeval_checks import CHECKERS, check_constraints


@pytest.mark.parametrize("ctype", list(CHECKERS))
def test_checker_exists(ctype: str):
    assert ctype in CHECKERS


def test_word_count_range():
    ok, total = check_constraints(
        "one two three four five", [{"type": "word_count_range", "min": 4, "max": 6}]
    )
    assert ok == 1 and total == 1


def test_json_only():
    ok, n = check_constraints('{"a": 1, "b": 2}', [{"type": "json_only", "keys": ["a", "b"]}])
    assert ok == 1 and n == 1


def test_forbidden_words():
    ok, n = check_constraints("hello world", [{"type": "forbidden_words", "words": ["bad"]}])
    assert ok == 1 and n == 1


def test_bullet_count():
    text = "- one\n- two\n- three\n"
    ok, total = check_constraints(text, [{"type": "bullet_count", "count": 3}])
    assert ok == 1 and total == 1


def test_all_lowercase():
    ok, _ = check_constraints(
        "all lower case here", [{"type": "all_lowercase", "min": 0, "max": 0}]
    )
    assert ok == 1


def test_must_include_keywords():
    ok, _ = check_constraints(
        "We need trust and a shared goal.",
        [{"type": "must_include_keywords", "keywords": ["trust", "goal"]}],
    )
    assert ok == 1


def test_section_headers():
    text = "## Overview\nx\n## Specs\ny"
    ok, _ = check_constraints(
        text, [{"type": "section_headers", "headers": ["## Overview", "## Specs"]}]
    )
    assert ok == 1


def test_ends_with_phrase():
    ok, _ = check_constraints(
        "done for today. sweet dreams.", [{"type": "ends_with_phrase", "phrase": "sweet dreams."}]
    )
    assert ok == 1
