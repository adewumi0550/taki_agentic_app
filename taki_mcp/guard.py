"""Runtime dose guard — the last line of defence.

The repo guard (taki_model/scripts/check_no_doses.sh) keeps doses out of the
source. This guard keeps them out of what a farmer actually receives. If the
model ever emits a number bound to a dose unit, the number is replaced with
the registry placeholder and the event is flagged so it shows up in the
conversation store.

Nothing here contains a literal dose; the patterns are built from character
classes so this file passes the repo guard too.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

PLACEHOLDER = "<DOSE_FROM_REGISTRY>"

_NUM = r"\d[\d.,]*"
_SP = r"\s*"
_PER = r"(?:/|per\s+|a\s+kowace\s+|kowane\s+)"

_PATTERNS = [
    # volume per volume: ml per litre, cc per litre, litres per drum
    rf"{_NUM}{_SP}(?:ml|mL|cc|l|L|lita|litre|liter)s?{_SP}{_PER}{_SP}(?:l|L|lita|litre|liter|drum|gal(?:lon)?|ruwa)",
    # mass per volume / area: g per litre, kg per hectare
    rf"{_NUM}{_SP}(?:g|kg|gram|grams|kilo)s?{_SP}{_PER}{_SP}(?:l|L|lita|litre|liter|ha|hectare|hekta|acre|kadada)",
    # volume per area
    rf"{_NUM}{_SP}(?:ml|mL|l|L|lita|litre|liter)s?{_SP}{_PER}{_SP}(?:ha|hectare|hekta|acre|kadada)",
    # household measures
    rf"{_NUM}{_SP}(?:sachet|capful|cap|tablespoon|teaspoon|cokali|murfi)s?{_SP}{_PER}",
    # intervals: pre-harvest waits (N days / kwanaki kafin girbi) and re-entry
    rf"{_NUM}{_SP}(?:days?|kwanaki|kwana|hours?|awa|sa'o'i)\s+(?:before|kafin|pre-?)\s*(?:harvest|girbi|re-?entry|shiga)",
    rf"(?:pre-?harvest|re-?entry)\s+interval\D{{0,12}}{_NUM}",
]
_RX = [re.compile(p, re.IGNORECASE) for p in _PATTERNS]


@dataclass(frozen=True)
class GuardResult:
    text: str
    triggered: bool
    matches: tuple[str, ...]


def apply(text: str) -> GuardResult:
    """Redact anything dose-shaped. Returns the safe text plus what was hit."""
    hits: list[str] = []

    def _redact(m: re.Match) -> str:
        hits.append(m.group(0))
        return PLACEHOLDER

    out = text
    for rx in _RX:
        out = rx.sub(_redact, out)
    return GuardResult(text=out, triggered=bool(hits), matches=tuple(hits))
