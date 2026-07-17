"""Rule-based parsing for the worker log workbook.

The source text is always retained.  This module only derives structured fields
that can be reviewed and corrected later.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, asdict
from typing import Optional


HOURS_RE = re.compile(
    r"(?P<hours>\d+(?:\.\d+)?)\s*h(?:ou)?r?s?\b", re.IGNORECASE
)
PAREN_HOURS_RE = re.compile(
    r"\(\s*(?P<hours>\d+(?:\.\d+)?)\s*h(?:ou)?r?s?\s*\)",
    re.IGNORECASE,
)
OT_RE = re.compile(
    r"\b(?:ot|overtime)\s*(?P<hours>\d+(?:\.\d+)?)\s*(?:h(?:ou)?r?s?)?\b",
    re.IGNORECASE,
)
MORE_HOURS_RE = re.compile(
    r"(?P<hours>\d+(?:\.\d+)?)\s*h(?:ou)?r?s?\s*more\b",
    re.IGNORECASE,
)
MONEY_RE = re.compile(
    r"\$\s*(?P<amount>\d+(?:\.\d+)?)\s*(?:dollars?)?\s*(?:more|extra)?",
    re.IGNORECASE,
)
HALF_DAY_RE = re.compile(r"\bhalf\s*day\b", re.IGNORECASE)
OFF_RE = re.compile(r"^\s*(?:off\b.*|no\s*work\b.*|休息.*)\s*$", re.IGNORECASE)
SEPARATOR_RE = re.compile(r"\s*(?:/|\+|,)\s*")


@dataclass
class ParsedLocation:
    name: str
    hours: Optional[float] = None


@dataclass
class ParseResult:
    status: str
    total_hours: Optional[float]
    locations: list[ParsedLocation]
    extra_pay: float
    original_text: str
    confidence: str
    warning: Optional[str] = None

    def to_dict(self) -> dict:
        result = asdict(self)
        result["locations"] = [asdict(item) for item in self.locations]
        return result


def normalize_space(value: str) -> str:
    return " ".join((value or "").replace("\u00a0", " ").split())


def normalize_name(value: str) -> str:
    value = unicodedata.normalize("NFKD", normalize_space(value)).encode(
        "ascii", "ignore"
    ).decode("ascii")
    return re.sub(r"[^a-z0-9]+", " ", value.lower()).strip()


def _clean_location(value: str) -> str:
    value = PAREN_HOURS_RE.sub("", value)
    value = MONEY_RE.sub("", value)
    value = OT_RE.sub("", value)
    value = MORE_HOURS_RE.sub("", value)
    value = HALF_DAY_RE.sub("", value)
    value = re.sub(
        r"\b\d+(?:\.\d+)?\s*h(?:ou)?r?s?\b",
        "",
        value,
        flags=re.IGNORECASE,
    )
    value = value.strip(" \t\r\n,;/+-")
    return normalize_space(value)


def _split_locations(text: str) -> list[str]:
    # Keep commas that are clearly part of an annotation out of the split.
    text = re.sub(r",?\s*\bOT\b", " OT ", text, flags=re.IGNORECASE)
    candidates = SEPARATOR_RE.split(text)
    return [item for item in (normalize_space(x) for x in candidates) if item]


def parse_work_cell(value: object) -> ParseResult:
    original = "" if value is None else str(value)
    text = normalize_space(original).replace("（", "(").replace("）", ")")

    if not text:
        return ParseResult(
            status="unknown",
            total_hours=None,
            locations=[],
            extra_pay=0,
            original_text=original,
            confidence="low",
            warning="Blank cell — confirm whether this means off or not recorded.",
        )

    if OFF_RE.match(text):
        return ParseResult(
            status="off",
            total_hours=0,
            locations=[],
            extra_pay=0,
            original_text=original,
            confidence="high",
        )

    if text.casefold() in {"out", "vacation", "holiday", "n/a", "na"}:
        return ParseResult(
            status="unknown",
            total_hours=None,
            locations=[],
            extra_pay=0,
            original_text=original,
            confidence="low",
            warning=f'Confirm what “{text}” means for this day.',
        )

    extra_pay = sum(float(match.group("amount")) for match in MONEY_RE.finditer(text))
    overtime = sum(float(match.group("hours")) for match in OT_RE.finditer(text))
    more_hours = sum(float(match.group("hours")) for match in MORE_HOURS_RE.finditer(text))
    half_day = bool(HALF_DAY_RE.search(text))

    parts = _split_locations(text)
    locations: list[ParsedLocation] = []
    explicit_hours: list[float] = []

    for part in parts:
        # An OT-only fragment belongs to the preceding location.
        if OT_RE.fullmatch(part) or MORE_HOURS_RE.fullmatch(part):
            continue
        # Remove additive annotations before looking for a location-level hour
        # amount. Otherwise "669 OT 2 hours" would incorrectly become a
        # two-hour day instead of the default eight plus two overtime.
        hour_source = OT_RE.sub("", part)
        hour_source = MORE_HOURS_RE.sub("", hour_source)
        hour_match = PAREN_HOURS_RE.search(hour_source)
        if not hour_match:
            # Also accept "1417 10 hours" and "lucretia 2.5h".
            matches = list(HOURS_RE.finditer(hour_source))
            hour_match = matches[-1] if matches else None
        hours = float(hour_match.group("hours")) if hour_match else None
        location = _clean_location(part)
        if location:
            locations.append(ParsedLocation(location, hours))
            if hours is not None:
                explicit_hours.append(hours)

    if explicit_hours:
        if len(explicit_hours) == len(locations):
            total_hours = sum(explicit_hours)
        elif len(locations) == 1:
            total_hours = explicit_hours[0]
        else:
            # Example: "1417 (6h) / 771" means two locations, but only the
            # total/default distribution is not fully specified.
            total_hours = max(8.0, sum(explicit_hours))
    elif half_day:
        total_hours = 4.0
    elif more_hours:
        total_hours = 8.0 + more_hours
    elif overtime:
        total_hours = 8.0 + overtime
    else:
        total_hours = 8.0

    warning = None
    confidence = "high"
    if "?" in text:
        confidence = "low"
        warning = "The location contains a question mark and needs confirmation."
    elif not locations:
        confidence = "low"
        warning = "No work location could be identified."
    elif explicit_hours and len(explicit_hours) != len(locations):
        confidence = "medium"
        warning = "Some locations do not have their own hour split."

    return ParseResult(
        status="worked",
        total_hours=round(total_hours, 2),
        locations=locations,
        extra_pay=round(extra_pay, 2),
        original_text=original,
        confidence=confidence,
        warning=warning,
    )


def format_work_cell(
    status: str,
    total_hours: Optional[float],
    locations: list[dict],
    extra_pay: float = 0,
) -> str:
    if status == "off":
        return "off"
    if status != "worked":
        return ""

    valid_locations = [item for item in locations if normalize_space(item.get("name", ""))]
    if not valid_locations:
        return ""

    def number(value: float) -> str:
        return str(int(value)) if float(value).is_integer() else str(value)

    all_split = all(item.get("hours") not in (None, "") for item in valid_locations)
    if len(valid_locations) > 1 and all_split:
        value = " / ".join(
            f"{normalize_space(item['name'])} ({number(float(item['hours']))}h)"
            for item in valid_locations
        )
    elif len(valid_locations) > 1:
        value = " / ".join(normalize_space(item["name"]) for item in valid_locations)
        if total_hours not in (None, 8, 8.0):
            value += f" ({number(float(total_hours))}h total)"
    else:
        value = normalize_space(valid_locations[0]["name"])
        if total_hours not in (None, 8, 8.0):
            value += f" ({number(float(total_hours))}h)"

    if extra_pay:
        value += f" (${number(float(extra_pay))} more)"
    return value
