import json
from collections import Counter
from pathlib import Path

from llmbench.toolcall_match import grade_case, grade_case_detail

ROOT = Path(__file__).resolve().parents[1]


def _tool(name: str, props: dict, required: list[str]) -> dict:
    return {
        "type": "function",
        "function": {
            "name": name,
            "description": name,
            "parameters": {"type": "object", "properties": props, "required": required},
        },
    }


def _msg(*calls: tuple[str, dict]) -> dict:
    return {
        "role": "assistant",
        "content": "",
        "tool_calls": [
            {"type": "function", "function": {"name": n, "arguments": json.dumps(a)}}
            for n, a in calls
        ],
    }


WEATHER = _tool(
    "get_weather",
    {"location": {"type": "string"}, "units": {"type": "string"}},
    ["location"],
)
CONVERT = _tool(
    "convert",
    {"value": {"type": "number"}, "to_unit": {"type": "string"}},
    ["value", "to_unit"],
)
TAGS = _tool(
    "tag_item",
    {
        "item_id": {"type": "integer"},
        "tags": {"type": "array", "items": {"type": "string"}},
    },
    ["item_id", "tags"],
)

SIMPLE = {
    "kind": "simple",
    "prompt": "Weather in Boston?",
    "tools": [WEATHER],
    "expected": [
        {
            "name": "get_weather",
            "arguments": {"location": ["Boston", "Boston, MA"]},
            "optional": {"units": ["celsius", "C"]},
        }
    ],
}


def test_acceptable_values_and_normalisation():
    assert grade_case(SIMPLE, _msg(("get_weather", {"location": "Boston"})))
    assert grade_case(SIMPLE, _msg(("get_weather", {"location": "  boston, ma. "})))
    assert not grade_case(SIMPLE, _msg(("get_weather", {"location": "Chicago"})))


def test_optional_params():
    assert grade_case(SIMPLE, _msg(("get_weather", {"location": "Boston", "units": "C"})))
    assert not grade_case(
        SIMPLE, _msg(("get_weather", {"location": "Boston", "units": "fahrenheit"}))
    )


def test_unknown_param_missing_required_wrong_function():
    ok, reason = grade_case_detail(
        SIMPLE, _msg(("get_weather", {"location": "Boston", "zip": "02108"}))
    )
    assert not ok and reason
    ok, reason = grade_case_detail(SIMPLE, _msg(("get_weather", {"units": "C"})))
    assert not ok and reason
    assert not grade_case(SIMPLE, _msg(("convert", {"value": 1, "to_unit": "km"})))
    assert not grade_case(SIMPLE, {"role": "assistant", "content": "It is sunny."})


def test_numbers_compare_by_value():
    case = {
        "kind": "simple",
        "prompt": "Convert 5 miles to km",
        "tools": [CONVERT],
        "expected": [{"name": "convert", "arguments": {"value": [5], "to_unit": ["km"]}}],
    }
    assert grade_case(case, _msg(("convert", {"value": 5.0, "to_unit": "km"})))
    assert not grade_case(case, _msg(("convert", {"value": 6, "to_unit": "km"})))


def test_parallel_order_insensitive():
    case = {
        "kind": "parallel",
        "prompt": "Weather in Boston and Paris",
        "tools": [WEATHER],
        "expected": [
            {"name": "get_weather", "arguments": {"location": ["Boston"]}},
            {"name": "get_weather", "arguments": {"location": ["Paris"]}},
        ],
    }
    fwd = _msg(("get_weather", {"location": "Boston"}), ("get_weather", {"location": "Paris"}))
    rev = _msg(("get_weather", {"location": "Paris"}), ("get_weather", {"location": "Boston"}))
    assert grade_case(case, fwd)
    assert grade_case(case, rev)
    assert not grade_case(case, _msg(("get_weather", {"location": "Boston"})))


def test_irrelevance_passes_only_without_calls():
    case = {
        "kind": "irrelevance",
        "prompt": "Book me a haircut",
        "tools": [WEATHER],
        "expected": [],
    }
    assert grade_case(case, {"role": "assistant", "content": "I can't book haircuts."})
    assert not grade_case(case, _msg(("get_weather", {"location": "Boston"})))


def test_arrays_compare_as_multisets():
    case = {
        "kind": "typed",
        "prompt": "Tag item 7 with red and blue",
        "tools": [TAGS],
        "expected": [
            {"name": "tag_item", "arguments": {"item_id": [7], "tags": [["red", "blue"]]}}
        ],
    }
    assert grade_case(case, _msg(("tag_item", {"item_id": 7, "tags": ["blue", "Red"]})))
    assert not grade_case(case, _msg(("tag_item", {"item_id": 7, "tags": ["red"]})))


def test_fixture_shape():
    cases = json.loads((ROOT / "fixtures" / "toolcall.json").read_text())
    assert len(cases) == 20
    assert Counter(c["kind"] for c in cases) == {
        "simple": 5,
        "multiple": 5,
        "parallel": 4,
        "irrelevance": 3,
        "typed": 3,
    }
    for c in cases:
        if c["kind"] == "irrelevance":
            assert c["expected"] == []
            continue
        for exp in c["expected"]:
            for vals in exp["arguments"].values():
                assert isinstance(vals, list) and vals
        if c["kind"] == "multiple":
            assert len(c["tools"]) >= 4
        if c["kind"] == "parallel":
            assert 2 <= len(c["expected"]) <= 3
