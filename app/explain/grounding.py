"""Grounding check: every number and date in generated text must come from the payload, and
no accusatory or promissory language is allowed."""

import re
from dataclasses import dataclass, field
from typing import Any

DATE_RE = re.compile(r"\b\d{4}-\d{2}-\d{2}\b")
# a number not glued to a word (so "SYNTH_09" or "v1" are not treated as numbers)
NUMBER_RE = re.compile(r"(?<![\w.])-?\d+(?:,\d{3})*(?:\.\d+)?(?![\w])")
BANNED_RE = re.compile(r"\b(manipulat\w*|fraud\w*|guarantee\w*)", re.IGNORECASE)


@dataclass
class GroundingResult:
    ok: bool
    problems: list[str] = field(default_factory=list)


def _collect(payload: Any, numbers: list[float], strings: list[str]) -> None:
    if isinstance(payload, bool):
        return
    if isinstance(payload, int | float):
        numbers.append(float(payload))
    elif isinstance(payload, str):
        strings.append(payload)
    elif isinstance(payload, dict):
        for v in payload.values():
            _collect(v, numbers, strings)
    elif isinstance(payload, list | tuple):
        for v in payload:
            _collect(v, numbers, strings)


def _number_ok(token: str, allowed: list[float]) -> bool:
    value = float(token.replace(",", ""))
    decimals = len(token.split(".")[1]) if "." in token else 0
    return any(round(abs(v), decimals) == abs(value) for v in allowed)


def check_grounding(text: str, payload: dict[str, Any]) -> GroundingResult:
    numbers: list[float] = []
    strings: list[str] = []
    _collect(payload, numbers, strings)
    problems: list[str] = []

    payload_dates = {d for s in strings for d in DATE_RE.findall(s)}
    # numbers that are part of payload strings (e.g. "previous 20 trading days") are grounded too
    numbers += [
        float(t.replace(",", "")) for s in strings for t in NUMBER_RE.findall(DATE_RE.sub(" ", s))
    ]
    for d in DATE_RE.findall(text):
        if d not in payload_dates:
            problems.append(f"date not in payload: {d}")
    for token in NUMBER_RE.findall(DATE_RE.sub(" ", text)):
        if not _number_ok(token, numbers):
            problems.append(f"number not in payload: {token}")
    for m in BANNED_RE.findall(text):
        problems.append(f"banned term: {m}")
    if not text.strip():
        problems.append("empty text")
    return GroundingResult(ok=not problems, problems=problems)
