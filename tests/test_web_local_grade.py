from llmbench.tasks.t12_web_local import _answers_match


def test_extra_keys_ignored():
    assert _answers_match({"fee_usd": 49}, {"fee_usd": 49, "note": "x"})


def test_string_casefold():
    assert _answers_match({"email": "help@bench.example"}, {"email": "  Help@Bench.Example "})


def test_non_dict_fails():
    assert not _answers_match({"fee_usd": 49}, [49])
