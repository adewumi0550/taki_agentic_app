"""DevFest Owerri 2026 quiz — page + shared leaderboard.

Single instance by design: the leaderboard lives in memory and is
mirrored to /tmp so a restart during the event does not lose the board.
Deploy with --max-instances 1 or players will see different boards.
"""
import json
import os
import re
import threading
import time
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, JSONResponse

HERE = Path(__file__).resolve().parent
STORE = Path(os.environ.get("BOARD_FILE", "/tmp/leaderboard.json"))
MAX_SCORE = 2000
_lock = threading.Lock()


def _load() -> list:
    try:
        return json.loads(STORE.read_text())
    except Exception:
        return []


_board = _load()
app = FastAPI(title="devfest-owerri-quiz")


@app.get("/health")
def health():
    return {"ok": True, "players": len(_board)}


@app.post("/score")
async def score(req: Request):
    body = await req.json()
    name = re.sub(r"[^\w .'-]", "", str(body.get("name", ""))).strip()[:24]
    pts = int(body.get("score") or 0)
    correct = int(body.get("correct") or 0)
    if not name or not (0 <= pts <= MAX_SCORE):
        return JSONResponse({"error": "bad entry"}, status_code=400)
    with _lock:
        # one entry per player: keep their best run
        prev = next((e for e in _board if e["name"].lower() == name.lower()), None)
        if prev:
            if pts > prev["score"]:
                prev.update(score=pts, correct=correct, ts=time.time())
        else:
            _board.append({"name": name, "score": pts, "correct": correct,
                           "ts": time.time()})
        _board.sort(key=lambda e: (-e["score"], e["ts"]))
        try:
            STORE.write_text(json.dumps(_board))
        except Exception:
            pass
        rank = next(i for i, e in enumerate(_board)
                    if e["name"].lower() == name.lower()) + 1
    return {"rank": rank, "players": len(_board), "board": _board[:10]}


@app.post("/reset")
async def reset(req: Request):
    """Clear the board. Token-gated: the service is public."""
    body = await req.json()
    want = os.environ.get("ADMIN_TOKEN")
    if not want or body.get("token") != want:
        return JSONResponse({"error": "nope"}, status_code=403)
    with _lock:
        _board.clear()
        try:
            STORE.write_text("[]")
        except Exception:
            pass
    return {"ok": True, "players": 0}


@app.get("/leaderboard")
def leaderboard():
    with _lock:
        return {"board": _board[:10], "players": len(_board)}


@app.get("/")
def page():
    return FileResponse(HERE / "quiz.html")
