"""Grade BFCL-style tool calls (names and acceptable argument values)."""

from __future__ import annotations

import json
import re
from itertools import permutations
from typing import Any

from llmbench.core import call_args

_TRAIL_PUNCT = ".,;:!?\"'"


def _norm_str(s: str) -> str:
    s = s.strip().casefold()
    s = re.sub(r"\s+", " ", s)
    return s.rstrip(_TRAIL_PUNCT).strip()


def _as_number(v: Any) -> float | None:
    if isinstance(v, bool) or v is None:
        return None
    if isinstance(v, int | float):
        return float(v)
    if isinstance(v, str):
        try:
            return float(v.strip())
        except ValueError:
            return None
    return None


def _norm_scalar(v: Any) -> Any:
    if isinstance(v, str):
        return _norm_str(v)
    if isinstance(v, float) and v.is_integer():
        return int(v)
    return v


def _norm_value(v: Any) -> Any:
    v = _norm_scalar(v)
    if isinstance(v, list):
        return [_norm_value(x) for x in v]
    if isinstance(v, dict):
        return {k: _norm_value(v[k]) for k in sorted(v)}
    return v


def _scalars_equal(expected: Any, actual: Any) -> bool:
    en, an = _as_number(expected), _as_number(actual)
    if en is not None and an is not None:
        return en == an
    if isinstance(expected, str) and isinstance(actual, str):
        return _norm_str(expected) == _norm_str(actual)
    if isinstance(expected, bool) and isinstance(actual, bool):
        return expected is actual
    return _norm_scalar(expected) == _norm_scalar(actual)


def args_match(expected: dict[str, Any], actual: dict[str, Any]) -> bool:
    exp = _norm_value(expected)
    act = _norm_value(actual)
    return exp == act


def calls_from_message(msg: dict[str, Any]) -> list[dict[str, Any]]:
    out = []
    for tc in msg.get("tool_calls") or []:
        fn = tc.get("function") or {}
        out.append({"name": fn.get("name"), "arguments": call_args(tc)})
    return out


def _fn_schema(case: dict[str, Any], name: str) -> tuple[dict[str, Any], list[str]]:
    for tool in case.get("tools") or []:
        fn = tool.get("function") or {}
        if fn.get("name") == name:
            params = fn.get("parameters") or {}
            return dict(params.get("properties") or {}), list(params.get("required") or [])
    return {}, []


def _array_alts(raw: Any) -> list[list[Any]]:
    if not isinstance(raw, list):
        return [[raw]]
    if not raw:
        return [[]]
    if all(isinstance(x, list) for x in raw):
        return raw
    return [raw]


def _item_equal(expected: Any, actual: Any, item_prop: dict[str, Any], ordered: bool) -> bool:
    typ = item_prop.get("type")
    if typ == "object" or isinstance(expected, dict):
        ok, _ = _match_object(expected, actual, item_prop, ordered)
        return ok
    if typ == "array" or isinstance(expected, list):
        if not isinstance(actual, list) or not isinstance(expected, list):
            return False
        return _match_array(expected, actual, item_prop.get("items") or {}, ordered)
    return _scalars_equal(expected, actual)


def _match_array(
    expected_list: list[Any], actual_list: list[Any], item_prop: dict[str, Any], ordered: bool
) -> bool:
    if len(expected_list) != len(actual_list):
        return False
    if ordered:
        return all(
            _item_equal(e, a, item_prop, ordered) for e, a in zip(expected_list, actual_list)
        )
    remaining = list(actual_list)
    for exp in expected_list:
        found: int | None = None
        for i, act in enumerate(remaining):
            if _item_equal(exp, act, item_prop, ordered):
                found = i
                break
        if found is None:
            return False
        remaining.pop(found)
    return True


def _match_object(
    expected_spec: dict[str, Any], actual: Any, schema_prop: dict[str, Any], ordered: bool
) -> tuple[bool, str]:
    if not isinstance(actual, dict):
        return False, "expected an object"
    nested_props = dict(schema_prop.get("properties") or {})
    nested_req = list(schema_prop.get("required") or [])
    if nested_props:
        for k in actual:
            if k not in nested_props:
                return False, f"unknown argument {k!r}"
    for k in nested_req:
        if k not in actual:
            return False, f"missing required argument {k!r}"
    for k, alts in expected_spec.items():
        if k not in actual:
            return False, f"missing required argument {k!r}"
        ok, reason = _match_value(alts, actual[k], nested_props.get(k) or {}, ordered, k)
        if not ok:
            return False, reason
    return True, ""


def _is_object_alts(expected_alts: Any, typ: str | None) -> bool:
    if typ == "object":
        return True
    if isinstance(expected_alts, dict):
        return True
    return (
        isinstance(expected_alts, list)
        and bool(expected_alts)
        and isinstance(expected_alts[0], dict)
    )


def _is_array_alts(expected_alts: Any, actual: Any, typ: str | None) -> bool:
    if typ == "array":
        return True
    return isinstance(actual, list) and isinstance(expected_alts, list)


def _match_value(
    expected_alts: Any, actual: Any, prop: dict[str, Any], ordered: bool, key: str
) -> tuple[bool, str]:
    typ = prop.get("type")
    if _is_object_alts(expected_alts, typ if isinstance(typ, str) else None):
        alts = expected_alts if isinstance(expected_alts, list) else [expected_alts]
        for alt in alts:
            if isinstance(alt, dict):
                ok, _ = _match_object(alt, actual, prop, ordered)
                if ok:
                    return True, ""
        return False, f"argument {key!r} object did not match"

    if _is_array_alts(expected_alts, actual, typ if isinstance(typ, str) else None):
        if not isinstance(actual, list):
            return False, f"argument {key!r} should be an array"
        for alt in _array_alts(expected_alts):
            if _match_array(alt, actual, prop.get("items") or {}, ordered):
                return True, ""
        return False, f"argument {key!r} value not acceptable"

    alts = expected_alts if isinstance(expected_alts, list) else [expected_alts]
    for alt in alts:
        if _scalars_equal(alt, actual):
            return True, ""
    return False, f"argument {key!r} value {actual!r} not acceptable"


def _match_call(exp: dict[str, Any], act: dict[str, Any], case: dict[str, Any]) -> tuple[bool, str]:
    if act.get("name") != exp.get("name"):
        return False, f"wrong function: got {act.get('name')!r}, expected {exp.get('name')!r}"

    props, required = _fn_schema(case, exp["name"])
    actual_args = act.get("arguments") or {}
    expected_args = exp.get("arguments") or {}
    optional = exp.get("optional") or {}
    ordered = bool(exp.get("ordered") or case.get("ordered"))

    if not isinstance(actual_args, dict):
        return False, "arguments are not an object"

    allowed = set(props) if props else set(expected_args) | set(optional)
    for k in actual_args:
        if k not in allowed:
            return False, f"unknown argument {k!r}"

    for k in required:
        if k not in actual_args:
            return False, f"missing required argument {k!r}"

    for k, alts in expected_args.items():
        if k not in actual_args:
            return False, f"missing required argument {k!r}"
        ok, reason = _match_value(alts, actual_args[k], props.get(k) or {}, ordered, k)
        if not ok:
            return False, reason

    for k, alts in optional.items():
        if k in actual_args:
            ok, reason = _match_value(alts, actual_args[k], props.get(k) or {}, ordered, k)
            if not ok:
                return False, reason

    return True, ""


def grade_case_detail(case: dict[str, Any], msg: dict[str, Any]) -> tuple[bool, str]:
    kind = case["kind"]
    try:
        calls = calls_from_message(msg)
    except (json.JSONDecodeError, TypeError, ValueError):
        return False, "invalid tool call arguments"

    if kind == "irrelevance":
        if calls:
            return False, f"expected no tool call, got {len(calls)}"
        return True, ""

    expected = case["expected"]

    if kind in {"simple", "multiple", "typed"}:
        if len(calls) != 1:
            return False, f"expected 1 tool call, got {len(calls)}"
        return _match_call(expected[0], calls[0], case)

    if kind == "parallel":
        if len(calls) != len(expected):
            return False, f"expected {len(expected)} tool calls, got {len(calls)}"
        for perm in permutations(calls):
            if all(_match_call(exp, act, case)[0] for exp, act in zip(expected, perm, strict=True)):
                return True, ""
        return False, "tool calls did not match expected (order-insensitive)"

    raise ValueError(f"unknown case kind {kind!r}")


def grade_case(case: dict[str, Any], msg: dict[str, Any]) -> bool:
    ok, _ = grade_case_detail(case, msg)
    return ok


def score_toolcall_cases(cases: list[dict], messages: list[dict]) -> float:
    if not cases:
        return 0.0
    passed = sum(1 for c, m in zip(cases, messages, strict=True) if grade_case(c, m))
    return passed / len(cases)
