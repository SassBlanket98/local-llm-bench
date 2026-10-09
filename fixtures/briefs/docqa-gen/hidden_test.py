from llmbench.docqa_gen import FACTS, handbook_for_target_tokens
from llmbench.tasks.t10_docqa import TARGETS


def ws(text: str) -> int:
    return len(text.split())


def test_targets():
    assert tuple(TARGETS) == (8000, 16000, 24000)


def test_deterministic():
    assert handbook_for_target_tokens(8000, ws) == handbook_for_target_tokens(8000, ws)


def test_never_exceeds_target_and_close_to_it():
    for target in (2000, 8000, 16000, 24000):
        doc, _ = handbook_for_target_tokens(target, ws)
        n = ws(doc)
        assert n <= target
        assert n >= 0.8 * target


def test_twelve_facts_interleaved():
    assert len(FACTS) == 12
    doc, _ = handbook_for_target_tokens(16000, ws)
    size = len(doc)
    orig, rev = [], []
    for key, _old, _new in FACTS:
        title = key.replace("_", " ").title()
        o = doc.find(f"## {title}\nOriginal policy:")
        r = doc.find(f"## {title} (revised)")
        assert o >= 0 and r >= 0, title
        orig.append(o)
        rev.append(r)
    assert len(set(orig + rev)) == 24
    assert max(orig) < 0.72 * size
    assert min(rev) > 0.66 * size
    assert max(orig) - min(orig) > 0.4 * size
    assert max(rev) - min(rev) > 0.15 * size
