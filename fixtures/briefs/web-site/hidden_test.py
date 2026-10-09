import json
from pathlib import Path

from llmbench.tasks.t12_web_local import _answers_match

ROOT = Path(__file__).resolve().parents[1]
SITE = ROOT / "fixtures" / "site"


def test_extra_keys_ignored():
    assert _answers_match({"fee_usd": 49}, {"fee_usd": 49, "note": "x"})


def test_string_casefold_strip():
    assert _answers_match({"email": "help@bench.example"}, {"email": "  Help@Bench.Example "})


def test_numbers_compare_numerically():
    assert _answers_match({"fee_usd": 49}, {"fee_usd": 49.0})
    assert not _answers_match({"fee_usd": 49}, {"fee_usd": 59})


def test_missing_key_and_non_dict_fail():
    assert not _answers_match({"sku": "AX-900", "fee_usd": 49}, {"sku": "AX-900"})
    assert not _answers_match({"fee_usd": 49}, [49])
    assert not _answers_match({"fee_usd": 49}, "49")


def test_site_has_required_pages():
    pages = sorted(p.relative_to(SITE).as_posix() for p in SITE.rglob("*.html"))
    assert len(pages) >= 12, pages
    for need in (
        "index.html",
        "pricing.html",
        "archived/pricing-2024.html",
        "support/contact-old.html",
        "contact.html",
        "about.html",
    ):
        assert need in pages, need
    assert any(p.startswith("blog/") for p in pages)
    assert len([p for p in pages if p.startswith("products/")]) >= 3


def test_archived_and_moved_pages():
    archived = (SITE / "archived" / "pricing-2024.html").read_text().lower()
    assert "archiv" in archived
    old = (SITE / "support" / "contact-old.html").read_text()
    assert "contact.html" in old and "moved" in old.lower()


def test_five_questions_with_dict_answers():
    cases = json.loads((ROOT / "fixtures" / "web_local.json").read_text())
    assert len(cases) == 5
    for c in cases:
        assert isinstance(c["question"], str) and "json" in c["question"].lower()
        assert isinstance(c["expected"], dict) and c["expected"]
