from llmbench.docqa_gen import FACTS, handbook_for_target_tokens, normalize_answer


def test_normalize():
    assert normalize_answer("  Hello, World! ") == "hello world"


def test_handbook_deterministic():
    def fake_tokenize(text: str) -> int:
        return len(text.split())

    a, la = handbook_for_target_tokens(800, fake_tokenize)
    b, lb = handbook_for_target_tokens(800, fake_tokenize)
    assert a == b
    assert la == lb


def test_handbook_token_count_at_most_target():
    def fake_tokenize(text: str) -> int:
        return len(text.split())

    for target in (800, 8000, 24000):
        doc, _ = handbook_for_target_tokens(target, fake_tokenize)
        assert fake_tokenize(doc) <= target


def test_facts_spread_at_distinct_positions():
    def fake_tokenize(text: str) -> int:
        return len(text.split())

    doc, _ = handbook_for_target_tokens(8000, fake_tokenize)
    positions: list[int] = []
    for key, _old, _new in FACTS:
        title = key.replace("_", " ").title()
        pos_old = doc.find(f"## {title}\nOriginal policy:")
        pos_new = doc.find(f"## {title} (revised)")
        assert pos_old >= 0 and pos_new >= 0
        positions.extend([pos_old, pos_new])
    assert len(positions) == len(set(positions))
    first_orig = min(positions[::2])
    first_rev = min(positions[1::2])
    assert first_rev > first_orig
    split = int(len(doc) * 0.65)
    assert all(positions[i] < split for i in range(0, len(positions), 2))
    assert all(positions[i] > split for i in range(1, len(positions), 2))
