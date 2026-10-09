import json
from pathlib import Path

import pytest

from llmbench.toolcall_match import grade_case, grade_case_detail

FIXTURE = Path(__file__).resolve().parents[1] / "fixtures" / "toolcall.json"
CASES = json.loads(FIXTURE.read_text())


def _msg(*calls: tuple[str, dict]) -> dict:
    if not calls:
        return {"content": "I cannot help with that using the available tools."}
    return {
        "tool_calls": [
            {"function": {"name": name, "arguments": json.dumps(args)}} for name, args in calls
        ]
    }


CORRECT = [
    _msg(("get_weather", {"location": "Boston"})),
    _msg(("send_email", {"to": "alice@example.com", "subject": "Project update"})),
    _msg(("set_timer", {"minutes": 5})),
    _msg(("web_search", {"query": "llama.cpp"})),
    _msg(("convert_units", {"value": 42, "from_unit": "miles", "to_unit": "km"})),
    _msg(("book_flight", {"destination": "Paris, France", "date": "2026-10-09"})),
    _msg(("add_to_list", {"item": "milk"})),
    _msg(("get_time", {"timezone": "Asia/Tokyo"})),
    _msg(("create_event", {"title": "Standup", "date": "2026-10-10", "time": "09:00"})),
    _msg(("play_music", {"genre": "jazz", "room": "living room"})),
    _msg(
        ("get_weather", {"location": "NYC"}),
        ("get_weather", {"location": "Boston, MA"}),
    ),
    _msg(
        ("send_email", {"to": "carol@example.com", "subject": "Sync"}),
        ("send_email", {"to": "bob@example.com", "subject": "Sync"}),
    ),
    _msg(("set_timer", {"minutes": 7}), ("set_timer", {"minutes": 3})),
    _msg(
        ("web_search", {"query": "llama.cpp vulkan"}),
        ("web_search", {"query": "python asyncio"}),
        ("web_search", {"query": "rust ownership"}),
    ),
    _msg(),
    _msg(),
    _msg(),
    _msg(
        (
            "schedule_meeting",
            {
                "date": "2026-03-01",
                "priority": "high",
                "title": "Quarterly Review",
                "attendees": ["bob@example.com", "alice@example.com"],
            },
        )
    ),
    _msg(("create_profile", {"profile": {"age": 30, "tags": ["ops", "admin"]}})),
    _msg(
        (
            "place_order",
            {
                "sku": "SKU-9912",
                "quantity": 2.0,
                "shipping": "express",
                "tags": ["fragile", "priority"],
            },
        )
    ),
]

WRONG = [
    _msg(("get_weather", {"location": "Seattle"})),
    _msg(("get_weather", {"location": "Boston"})),
    _msg(("set_timer", {})),
    _msg(("web_search", {"query": "llama.cpp", "site": "github.com"})),
    _msg(("convert_units", {"value": 42, "from_unit": "miles", "to_unit": "meters"})),
    _msg(("book_hotel", {"city": "Paris", "check_in": "2026-10-09"})),
    _msg(("order_grocery", {"item": "milk"})),
    _msg(("get_time", {"timezone": "Osaka"})),
    _msg(("create_event", {"title": "Standup", "date": "2026-10-10"})),
    _msg(("play_music", {"genre": "jazz", "room": "living room", "shuffle": True})),
    _msg(
        ("get_weather", {"location": "Boston"}),
        ("get_weather", {"location": "Chicago"}),
    ),
    _msg(("send_email", {"to": "bob@example.com", "subject": "Sync"})),
    _msg(("set_timer", {"minutes": 3}), ("set_timer", {"minutes": 8})),
    _msg(
        ("web_search", {"query": "python asyncio"}),
        ("web_search", {"query": "rust ownership"}),
    ),
    _msg(("get_weather", {"location": "Tokyo"})),
    _msg(("send_email", {"to": "host@example.com", "subject": "Reservation"})),
    _msg(("play_music", {"genre": "silence", "room": "kitchen"})),
    _msg(
        (
            "schedule_meeting",
            {
                "date": "2026-03-01",
                "priority": "urgent",
                "title": "Quarterly Review",
                "attendees": ["alice@example.com", "bob@example.com"],
            },
        )
    ),
    _msg(("create_profile", {"profile": {"age": 30, "tags": ["admin", "ops"], "nickname": "x"}})),
    _msg(
        (
            "place_order",
            {
                "sku": "SKU-9912",
                "quantity": 2,
                "shipping": "express",
                "tags": ["priority", "fragile"],
            },
        )
    ),
]


def _ids(i: int) -> str:
    return f"{i + 1}_{CASES[i]['kind']}"


@pytest.mark.parametrize("i", range(20), ids=_ids)
def test_correct_call_passes(i):
    ok, reason = grade_case_detail(CASES[i], CORRECT[i])
    assert ok, reason


@pytest.mark.parametrize("i", range(20), ids=_ids)
def test_wrong_call_fails(i):
    ok, reason = grade_case_detail(CASES[i], WRONG[i])
    assert not ok
    assert reason


def test_parallel_order_insensitive():
    case = CASES[10]
    forward = _msg(
        ("get_weather", {"location": "Boston"}),
        ("get_weather", {"location": "New York City"}),
    )
    reverse = _msg(
        ("get_weather", {"location": "New York"}),
        ("get_weather", {"location": "Boston, Massachusetts"}),
    )
    assert grade_case(case, forward)
    assert grade_case(case, reverse)


def test_optional_param_omitted_passes():
    assert grade_case(CASES[0], _msg(("get_weather", {"location": "Boston"})))


def test_optional_param_matching_passes():
    assert grade_case(CASES[0], _msg(("get_weather", {"location": "Boston", "units": "C"})))


def test_optional_param_wrong_fails():
    ok, reason = grade_case_detail(
        CASES[0], _msg(("get_weather", {"location": "Boston", "units": "kelvin"}))
    )
    assert not ok
    assert "units" in reason


def test_unlisted_schema_optional_allowed():
    assert grade_case(
        CASES[1],
        _msg(
            (
                "send_email",
                {
                    "to": "alice@example.com",
                    "subject": "Project update",
                    "body": "Hello Alice, here is the project update.",
                },
            )
        ),
    )


def test_wrong_function_fails():
    ok, reason = grade_case_detail(CASES[5], WRONG[5])
    assert not ok
    assert "wrong function" in reason


def test_wrong_value_fails():
    ok, reason = grade_case_detail(CASES[4], WRONG[4])
    assert not ok
    assert "to_unit" in reason


def test_missing_required_fails():
    ok, reason = grade_case_detail(CASES[2], WRONG[2])
    assert not ok
    assert "missing required" in reason


def test_unknown_param_fails():
    ok, reason = grade_case_detail(CASES[3], WRONG[3])
    assert not ok
    assert "unknown argument" in reason


def test_string_normalisation():
    assert grade_case(CASES[0], _msg(("get_weather", {"location": "  Boston,  MA. "})))


def test_fixture_kind_mix():
    kinds = [c["kind"] for c in CASES]
    assert kinds.count("simple") == 5
    assert kinds.count("multiple") == 5
    assert kinds.count("parallel") == 4
    assert kinds.count("irrelevance") == 3
    assert kinds.count("typed") == 3
