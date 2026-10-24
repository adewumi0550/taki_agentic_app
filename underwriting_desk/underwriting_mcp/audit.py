"""The decision log. Written BEFORE a result is returned.

There is no path where a tool ran and nothing recorded it.
"""
import json
import time
from pathlib import Path

LOG = Path("decision_log.jsonl")


def log_call(tool: str, file_id: str, result: dict) -> None:
    LOG.open("a").write(
        json.dumps({"ts": time.time(), "tool": tool, "file_id": file_id, "result": result})
        + "\n"
    )
