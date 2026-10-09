from llmbench.report import _fmt_ms, _fmt_tok_s


def test_fmt_tok_s_integer():
    assert _fmt_tok_s(21544.062533461827) == "21544"


def test_fmt_ms_one_decimal():
    assert _fmt_ms(12.3456) == "12.3"
