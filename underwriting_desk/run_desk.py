"""Run the underwriting desk on one loan file, end to end.

    python run_desk.py clean_file
    python run_desk.py conflict_file
    python run_desk.py conflict_file --sequential

Starts the MCP server locally, fans the four specialists out across the
file, reconciles, and prints a trace with per-agent timings.
"""
import argparse
import asyncio
import logging
import os
import socket
import subprocess
import sys
import time
import warnings
from pathlib import Path

# a live demo should print the desk, not the SDK
warnings.filterwarnings("ignore")
for _noisy in ("google", "google_genai", "google.adk", "google.auth", "mcp"):
    logging.getLogger(_noisy).setLevel(logging.ERROR)

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / "underwriting_agent"))

PORT = int(os.environ.get("PORT", "8080"))
os.environ.setdefault("MCP_URL", f"http://127.0.0.1:{PORT}/mcp")

DIM, BOLD, RESET = "\033[2m", "\033[1m", "\033[0m"


def start_mcp() -> subprocess.Popen:
    env = {**os.environ, "PORT": str(PORT), "HOST": "127.0.0.1"}
    proc = subprocess.Popen(
        [sys.executable, str(ROOT / "underwriting_mcp" / "server.py")],
        env=env,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    for _ in range(100):
        if proc.poll() is not None:
            raise SystemExit("underwriting-mcp failed to start")
        with socket.socket() as s:
            s.settimeout(0.2)
            if s.connect_ex(("127.0.0.1", PORT)) == 0:
                return proc
        time.sleep(0.1)
    proc.terminate()
    raise SystemExit(f"underwriting-mcp did not come up on :{PORT}")


async def run(file_id: str, sequential: bool) -> int:
    from google.adk.runners import InMemoryRunner
    from google.genai import types

    import agent

    desk = agent.build_sequential_desk() if sequential else agent.build_desk()
    runner = InMemoryRunner(agent=desk, app_name="underwriting_desk")
    session = await runner.session_service.create_session(
        app_name="underwriting_desk", user_id="demo"
    )

    mode = "SEQUENTIAL" if sequential else "CONCURRENT"
    print(f"\n{BOLD}underwriting desk{RESET}  file_id={file_id}  mode={mode}\n")

    started: dict[str, float] = {}
    t0 = time.monotonic()
    async for event in runner.run_async(
        user_id="demo",
        session_id=session.id,
        new_message=types.Content(
            role="user",
            parts=[types.Part(text=f"Underwrite this loan file. file_id={file_id}")],
        ),
    ):
        who = event.author
        if who not in started:
            started[who] = time.monotonic() - t0
            print(f"  {DIM}t+{started[who]:5.2f}s{RESET}  {who} started")
        for call in event.get_function_calls() or []:
            print(f"  {DIM}        {RESET}  {DIM}{who} -> {call.name}(){RESET}")
    elapsed = time.monotonic() - t0

    final = await runner.session_service.get_session(
        app_name="underwriting_desk", user_id="demo", session_id=session.id
    )
    memo = final.state.get("memo", "(no memo produced)")

    print(f"\n{BOLD}--- DECISION MEMO " + "-" * 50 + f"{RESET}\n")
    print(memo.strip())
    print(f"\n{BOLD}" + "-" * 68 + f"{RESET}")
    print(f"wall clock: {BOLD}{elapsed:.1f}s{RESET}  ({mode.lower()})")

    reported = [a for a in started if a.endswith("_agent")]
    print(f"specialists reporting: {len(reported)}/4  {', '.join(sorted(reported))}")
    if len(reported) < 4:
        print(f"{BOLD}INCOMPLETE — a specialist did not report{RESET}")
    return 0 if len(reported) == 4 else 1


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("file_id", nargs="?", default="clean_file")
    p.add_argument("--sequential", action="store_true")
    args = p.parse_args()

    if not (ROOT / "fixtures" / f"{args.file_id}.json").exists():
        raise SystemExit(f"no such fixture: fixtures/{args.file_id}.json")

    mcp = start_mcp()
    try:
        return asyncio.run(run(args.file_id, args.sequential))
    finally:
        mcp.terminate()
        mcp.wait(timeout=10)


if __name__ == "__main__":
    sys.exit(main())
