"""statements — reads synthetic fixture data only. No real applicant data, ever."""
import json
from pathlib import Path

FIXTURES = Path(__file__).resolve().parents[2] / "fixtures"


def _load(file_id: str) -> dict:
    return json.loads((FIXTURES / f"{file_id}.json").read_text())["statements"]


def read(file_id: str) -> dict:
    return _load(file_id)
