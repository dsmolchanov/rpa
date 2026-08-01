#!/usr/bin/env python3
"""Fail-closed response contracts for the pilot-v2 judge roles.

The validator deliberately uses only the Python standard library.  It
accepts one JSON object, applies resource limits before interpreting it, and
then enforces the role-specific shape and cross-field invariants.  The
matching contract document is suitable for inclusion in an atomic seal.
"""

import copy
import json
import unicodedata
from decimal import Decimal


RESPONSE_SCHEMA_VERSION = "pilot-v2"

MAX_RESPONSE_BYTES = 1024 * 1024
MAX_NESTING_DEPTH = 32
MAX_TOTAL_LIST_ITEMS = 2000
MAX_STRING_LENGTH = 20000

SCORER_KEYS = ("coverage", "relevance", "synthesis", "total", "summary")
SCORER_COMPONENT_KEYS = ("score", "rationale")

VERIFIER_KEYS = (
    "verifiable_claims",
    "supported_claims",
    "unsupported_claims",
    "unverifiable_claims",
    "claim_ledger",
    "critical_errors",
    "critical_error_count",
    "summary",
)
CLAIM_KEYS = ("claim", "candidate_citations", "status", "evidence", "rationale")
CLAIM_STATUSES = ("supported", "unsupported", "unverifiable")
CRITICAL_ERROR_KEYS = ("proposition", "category", "rationale", "evidence")
CRITICAL_ERROR_CATEGORIES = (
    "architecture",
    "control_flow",
    "security_auth",
    "data_loss",
    "source_of_truth",
    "runtime_config",
    "api_compatibility",
    "decision_status",
)


class JudgeResponseError(ValueError):
    """The judge response is malformed or violates its sealed contract."""


def _reject_constant(token):
    raise JudgeResponseError(
        f"non-finite numeric literal is not permitted: {token}")


def _object_without_duplicates(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise JudgeResponseError("duplicate object key is not permitted")
        result[key] = value
    return result


def _parse_one_object(text):
    if not isinstance(text, str):
        raise JudgeResponseError("response must be text containing one JSON object")
    try:
        encoded = text.encode("utf-8")
    except UnicodeEncodeError:
        raise JudgeResponseError("response is not valid UTF-8 text") from None
    if len(encoded) > MAX_RESPONSE_BYTES:
        raise JudgeResponseError(
            f"response exceeds {MAX_RESPONSE_BYTES} UTF-8 bytes")

    try:
        value = json.loads(
            text,
            object_pairs_hook=_object_without_duplicates,
            parse_constant=_reject_constant,
            parse_float=Decimal,
        )
    except JudgeResponseError:
        raise
    except (json.JSONDecodeError, RecursionError, ValueError, ArithmeticError) as exc:
        message = str(exc).splitlines()[0]
        raise JudgeResponseError(
            f"response is not exactly one valid JSON value: {message}") from None

    if not isinstance(value, dict):
        raise JudgeResponseError("response root must be one JSON object")
    _enforce_resource_limits(value)
    return value


def _enforce_resource_limits(value):
    total_list_items = 0
    stack = [(value, 1)]
    while stack:
        current, depth = stack.pop()
        if isinstance(current, str):
            if len(current) > MAX_STRING_LENGTH:
                raise JudgeResponseError(
                    f"string exceeds {MAX_STRING_LENGTH} characters")
            continue
        if isinstance(current, dict):
            if depth > MAX_NESTING_DEPTH:
                raise JudgeResponseError(
                    f"JSON nesting exceeds {MAX_NESTING_DEPTH}")
            for key, child in current.items():
                if len(key) > MAX_STRING_LENGTH:
                    raise JudgeResponseError(
                        f"string exceeds {MAX_STRING_LENGTH} characters")
                stack.append((child, depth + 1))
            continue
        if isinstance(current, list):
            if depth > MAX_NESTING_DEPTH:
                raise JudgeResponseError(
                    f"JSON nesting exceeds {MAX_NESTING_DEPTH}")
            total_list_items += len(current)
            if total_list_items > MAX_TOTAL_LIST_ITEMS:
                raise JudgeResponseError(
                    f"response exceeds {MAX_TOTAL_LIST_ITEMS} total list items")
            stack.extend((child, depth + 1) for child in current)


def _exact_keys(value, expected, location):
    if not isinstance(value, dict):
        raise JudgeResponseError(f"{location} must be an object")
    expected_set = set(expected)
    actual_set = set(value)
    missing = sorted(expected_set - actual_set)
    extra = sorted(actual_set - expected_set)
    defects = []
    if missing:
        defects.append("missing " + ", ".join(missing))
    if extra:
        names = [repr(name[:40]) for name in extra[:5]]
        defects.append("unexpected " + ", ".join(names))
    if defects:
        raise JudgeResponseError(f"{location}: {'; '.join(defects)}")


def _nonempty_string(value, location):
    if not isinstance(value, str):
        raise JudgeResponseError(f"{location} must be a string")
    if not value.strip():
        raise JudgeResponseError(f"{location} must be nonempty")
    return value


def _string_array(value, location):
    if not isinstance(value, list):
        raise JudgeResponseError(f"{location} must be an array of strings")
    for index, item in enumerate(value):
        _nonempty_string(item, f"{location}[{index}]")
    return value


def _score_ticks(value, maximum, location):
    if isinstance(value, bool) or not isinstance(value, (int, Decimal)):
        raise JudgeResponseError(f"{location} must be a finite numeric score")
    if isinstance(value, Decimal):
        if not value.is_finite():
            raise JudgeResponseError(f"{location} must be finite")
        numeric = value
    else:
        numeric = Decimal(value)

    # Reject the range before converting the decimal to a rational.  A
    # compact literal such as 1e100000000 otherwise asks
    # Decimal.as_integer_ratio() to materialize an enormous power of ten,
    # defeating the response byte limit with CPU/memory amplification.
    if numeric < 0 or numeric > maximum:
        raise JudgeResponseError(f"{location} must be between 0 and {maximum}")
    scaled = numeric * 4
    if scaled != scaled.to_integral_value():
        raise JudgeResponseError(f"{location} must be a quarter-point score")
    return int(scaled)


def _ticks_number(ticks):
    return ticks // 4 if ticks % 4 == 0 else ticks / 4


def _validate_scorer(value):
    _exact_keys(value, SCORER_KEYS, "scorer response")
    maxima = {"coverage": 4, "relevance": 3, "synthesis": 3}
    component_ticks = {}
    for component, maximum in maxima.items():
        item = value[component]
        _exact_keys(item, SCORER_COMPONENT_KEYS, component)
        ticks = _score_ticks(item["score"], maximum, f"{component}.score")
        _nonempty_string(item["rationale"], f"{component}.rationale")
        component_ticks[component] = ticks
        item["score"] = _ticks_number(ticks)

    total_ticks = _score_ticks(value["total"], 10, "total")
    if total_ticks != sum(component_ticks.values()):
        raise JudgeResponseError(
            "total must exactly equal the three component scores")
    value["total"] = _ticks_number(total_ticks)
    _nonempty_string(value["summary"], "summary")
    return value


def _nonnegative_int(value, location):
    if isinstance(value, bool) or not isinstance(value, int):
        raise JudgeResponseError(f"{location} must be a nonnegative integer")
    if value < 0:
        raise JudgeResponseError(f"{location} must be a nonnegative integer")
    return value


def _normalized_proposition(value):
    normalized = unicodedata.normalize("NFKC", value).lower()
    normalized = " ".join(normalized.split())
    while normalized and unicodedata.category(normalized[-1]).startswith("P"):
        normalized = normalized[:-1].rstrip()
    return normalized


def _validate_verifier(value):
    _exact_keys(value, VERIFIER_KEYS, "verifier response")
    count_names = (
        "verifiable_claims",
        "supported_claims",
        "unsupported_claims",
        "unverifiable_claims",
        "critical_error_count",
    )
    for name in count_names:
        _nonnegative_int(value[name], name)

    claim_sum = (
        value["supported_claims"]
        + value["unsupported_claims"]
        + value["unverifiable_claims"]
    )
    if value["verifiable_claims"] != claim_sum:
        raise JudgeResponseError(
            "verifiable_claims must equal supported + unsupported + unverifiable")

    ledger = value["claim_ledger"]
    if not isinstance(ledger, list):
        raise JudgeResponseError("claim_ledger must be an array")
    if len(ledger) != value["verifiable_claims"]:
        raise JudgeResponseError(
            "claim_ledger length must equal verifiable_claims")

    status_counts = {status: 0 for status in CLAIM_STATUSES}
    for index, claim in enumerate(ledger):
        location = f"claim_ledger[{index}]"
        _exact_keys(claim, CLAIM_KEYS, location)
        _nonempty_string(claim["claim"], f"{location}.claim")
        citations = _string_array(
            claim["candidate_citations"], f"{location}.candidate_citations")
        status = claim["status"]
        if not isinstance(status, str) or status not in CLAIM_STATUSES:
            raise JudgeResponseError(
                f"{location}.status must be supported, unsupported, or unverifiable")
        evidence = _string_array(claim["evidence"], f"{location}.evidence")
        _nonempty_string(claim["rationale"], f"{location}.rationale")
        if status == "supported" and (not citations or not evidence):
            raise JudgeResponseError(
                f"{location}: supported claims require citations and evidence")
        status_counts[status] += 1

    for status in CLAIM_STATUSES:
        expected = value[f"{status}_claims"]
        if status_counts[status] != expected:
            raise JudgeResponseError(
                f"claim_ledger {status} count must equal {status}_claims")

    critical_errors = value["critical_errors"]
    if not isinstance(critical_errors, list):
        raise JudgeResponseError("critical_errors must be an array")
    if len(critical_errors) != value["critical_error_count"]:
        raise JudgeResponseError(
            "critical_error_count must equal critical_errors length")

    normalized_propositions = set()
    for index, critical in enumerate(critical_errors):
        location = f"critical_errors[{index}]"
        _exact_keys(critical, CRITICAL_ERROR_KEYS, location)
        proposition = _nonempty_string(
            critical["proposition"], f"{location}.proposition")
        category = critical["category"]
        if (
            not isinstance(category, str)
            or category not in CRITICAL_ERROR_CATEGORIES
        ):
            raise JudgeResponseError(f"{location}.category is not permitted")
        _nonempty_string(critical["rationale"], f"{location}.rationale")
        evidence = _string_array(
            critical["evidence"], f"{location}.evidence")
        if not evidence:
            raise JudgeResponseError(
                f"{location}.evidence must be nonempty")

        normalized = _normalized_proposition(proposition)
        if not normalized:
            raise JudgeResponseError(
                f"{location}.proposition has no normalized content")
        if normalized in normalized_propositions:
            raise JudgeResponseError(
                "critical error propositions must be unique after normalization")
        normalized_propositions.add(normalized)

    _nonempty_string(value["summary"], "summary")
    return value


def validate_response(text, role):
    """Parse and validate one scorer or verifier response.

    ``role`` is exactly ``"scorer"`` or ``"verifier"``.  The returned
    dictionary contains only ordinary JSON-serializable values; scorer
    numbers are canonicalized from exact decimal input after validation.
    """

    value = _parse_one_object(text)
    if role == "scorer":
        return _validate_scorer(value)
    if role == "verifier":
        return _validate_verifier(value)
    raise JudgeResponseError("role must be 'scorer' or 'verifier'")


def _object_schema(required, properties):
    return {
        "type": "object",
        "required": list(required),
        "additionalProperties": False,
        "properties": properties,
    }


def _score_component_schema(maximum):
    return _object_schema(
        SCORER_COMPONENT_KEYS,
        {
            "score": {
                "type": "number",
                "minimum": 0,
                "maximum": maximum,
                "multipleOf": 0.25,
            },
            "rationale": {"type": "string", "minLength": 1},
        },
    )


_SCORER_SCHEMA = _object_schema(
    SCORER_KEYS,
    {
        "coverage": _score_component_schema(4),
        "relevance": _score_component_schema(3),
        "synthesis": _score_component_schema(3),
        "total": {
            "type": "number",
            "minimum": 0,
            "maximum": 10,
            "multipleOf": 0.25,
        },
        "summary": {"type": "string", "minLength": 1},
    },
)

_STRING_ARRAY_SCHEMA = {
    "type": "array",
    "items": {"type": "string", "minLength": 1},
}
_NONNEGATIVE_INTEGER_SCHEMA = {"type": "integer", "minimum": 0}

_VERIFIER_SCHEMA = _object_schema(
    VERIFIER_KEYS,
    {
        "verifiable_claims": _NONNEGATIVE_INTEGER_SCHEMA,
        "supported_claims": _NONNEGATIVE_INTEGER_SCHEMA,
        "unsupported_claims": _NONNEGATIVE_INTEGER_SCHEMA,
        "unverifiable_claims": _NONNEGATIVE_INTEGER_SCHEMA,
        "claim_ledger": {
            "type": "array",
            "items": _object_schema(
                CLAIM_KEYS,
                {
                    "claim": {"type": "string", "minLength": 1},
                    "candidate_citations": _STRING_ARRAY_SCHEMA,
                    "status": {"type": "string", "enum": list(CLAIM_STATUSES)},
                    "evidence": _STRING_ARRAY_SCHEMA,
                    "rationale": {"type": "string", "minLength": 1},
                },
            ),
        },
        "critical_errors": {
            "type": "array",
            "items": _object_schema(
                CRITICAL_ERROR_KEYS,
                {
                    "proposition": {"type": "string", "minLength": 1},
                    "category": {
                        "type": "string",
                        "enum": list(CRITICAL_ERROR_CATEGORIES),
                    },
                    "rationale": {"type": "string", "minLength": 1},
                    "evidence": {
                        "type": "array",
                        "minItems": 1,
                        "items": {"type": "string", "minLength": 1},
                    },
                },
            ),
        },
        "critical_error_count": _NONNEGATIVE_INTEGER_SCHEMA,
        "summary": {"type": "string", "minLength": 1},
    },
)


def contract_schema(role):
    """Return the complete, JSON-serializable sealed contract document."""

    if role == "scorer":
        schema = _SCORER_SCHEMA
        semantic_constraints = [
            (
                "all textual fields are nonempty after trimming "
                "whitespace"
            ),
            (
                "total quarter-ticks equal coverage + relevance + "
                "synthesis quarter-ticks"
            ),
        ]
    elif role == "verifier":
        schema = _VERIFIER_SCHEMA
        semantic_constraints = [
            (
                "all textual fields and string-array items are nonempty "
                "after trimming whitespace"
            ),
            (
                "verifiable_claims = supported_claims + "
                "unsupported_claims + unverifiable_claims"
            ),
            "claim_ledger length = verifiable_claims",
            "claim_ledger status counts equal their root count fields",
            (
                "supported ledger entries have nonempty "
                "candidate_citations and evidence"
            ),
            "critical_error_count = critical_errors length",
            (
                "critical error propositions are unique after NFKC, "
                "lowercase, whitespace collapse, and terminal-punctuation "
                "removal"
            ),
        ]
    else:
        raise JudgeResponseError("role must be 'scorer' or 'verifier'")

    return {
        "response_schema_version": RESPONSE_SCHEMA_VERSION,
        "role": role,
        "transport": {
            "encoding": "UTF-8",
            "top_level": "exactly one JSON object",
            "duplicate_keys": "reject",
            "non_finite_numbers": "reject",
        },
        "limits": {
            "max_utf8_bytes": MAX_RESPONSE_BYTES,
            "max_nesting_depth": MAX_NESTING_DEPTH,
            "max_total_list_items": MAX_TOTAL_LIST_ITEMS,
            "max_string_characters": MAX_STRING_LENGTH,
        },
        "schema": copy.deepcopy(schema),
        "semantic_constraints": semantic_constraints,
    }


if __name__ == "__main__":
    scorer = json.dumps({
        "coverage": {"score": 4, "rationale": "complete"},
        "relevance": {"score": 2.75, "rationale": "focused"},
        "synthesis": {"score": 3, "rationale": "coherent"},
        "total": 9.75,
        "summary": "valid scorer response",
    })
    verifier = json.dumps({
        "verifiable_claims": 1,
        "supported_claims": 1,
        "unsupported_claims": 0,
        "unverifiable_claims": 0,
        "claim_ledger": [{
            "claim": "A claim",
            "candidate_citations": ["module.py:1"],
            "status": "supported",
            "evidence": ["module.py:1 confirms it"],
            "rationale": "directly supported",
        }],
        "critical_errors": [],
        "critical_error_count": 0,
        "summary": "valid verifier response",
    })
    validate_response(scorer, "scorer")
    validate_response(verifier, "verifier")
    for exponent in ("1e100000000", "1e-100000000"):
        hostile = json.loads(scorer)
        hostile["coverage"]["score"] = exponent
        hostile_text = json.dumps(hostile).replace(
            f'"{exponent}"', exponent, 1)
        try:
            validate_response(hostile_text, "scorer")
        except JudgeResponseError:
            pass
        else:
            raise AssertionError("extreme Decimal exponent was accepted")
    json.dumps(contract_schema("scorer"), allow_nan=False)
    json.dumps(contract_schema("verifier"), allow_nan=False)
    print("judge_contract self-test: PASS")
