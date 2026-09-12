#!/usr/bin/env python3
"""Run the 20 Hausa agronomy prompts against either backend — or both at once.

Prints latency, token counts and the model's output. With two backends it
prints them side by side so local and Cloud Run can be compared directly.

There is no scoring harness here on purpose. Week 1 is about seeing what the
model actually does with Hausa, which MODELS.md section 4 records as
UNVERIFIED. Judgement stays with a human reading the output.

    python taki_model/evals/run_evals.py --backend local
    python taki_model/evals/run_evals.py --backend cloudrun
    python taki_model/evals/run_evals.py --backend both --limit 5
"""

from __future__ import annotations

import argparse
import json
import shutil
import sys
import textwrap
from dataclasses import dataclass, asdict
from pathlib import Path

PKG_ROOT = Path(__file__).resolve().parent.parent
REPO_ROOT = PKG_ROOT.parent
sys.path.insert(0, str(PKG_ROOT / "src"))

import client as taki_client  # noqa: E402  (needs the path above)

PROMPTS_PATH = PKG_ROOT / "evals" / "prompts.jsonl"
OUT_DIR = REPO_ROOT / ".eval_out"


@dataclass
class Result:
    id: str
    category: str
    crop: str
    backend: str
    prompt: str
    output: str
    latency_s: float
    prompt_tokens: int | None
    completion_tokens: int | None
    error: str | None = None


def load_prompts(limit: int | None) -> list[dict]:
    rows = [json.loads(line) for line in
            PROMPTS_PATH.read_text(encoding="utf-8").splitlines() if line.strip()]
    return rows[:limit] if limit else rows


def run_one(row: dict, backend: str) -> Result:
    try:
        reply = taki_client.chat(row["prompt"], backend_name=backend)
        return Result(
            id=row["id"], category=row["category"], crop=row.get("crop", ""),
            backend=backend, prompt=row["prompt"], output=reply.text,
            latency_s=reply.latency_s, prompt_tokens=reply.prompt_tokens,
            completion_tokens=reply.completion_tokens,
        )
    except Exception as exc:  # a dead backend should not kill the whole run
        return Result(
            id=row["id"], category=row["category"], crop=row.get("crop", ""),
            backend=backend, prompt=row["prompt"], output="",
            latency_s=0.0, prompt_tokens=None, completion_tokens=None,
            error=f"{type(exc).__name__}: {exc}",
        )


def _cell(text: str, width: int) -> list[str]:
    lines: list[str] = []
    for para in (text or "(no output)").splitlines() or [""]:
        lines.extend(textwrap.wrap(para, width) or [""])
    return lines


def print_single(results: list[Result], term_width: int) -> None:
    for r in results:
        print("=" * term_width)
        print(f"{r.id}  [{r.category}/{r.crop}]  backend={r.backend}")
        print("-" * term_width)
        print("PROMPT (ha):")
        for line in _cell(r.prompt, term_width - 2):
            print(f"  {line}")
        print()
        if r.error:
            print(f"ERROR: {r.error}")
        else:
            print("OUTPUT:")
            for line in _cell(r.output, term_width - 2):
                print(f"  {line}")
        print()
        print(f"latency={r.latency_s:.2f}s  "
              f"prompt_tokens={r.prompt_tokens}  completion_tokens={r.completion_tokens}")
    print("=" * term_width)


def print_side_by_side(by_backend: dict[str, list[Result]], term_width: int) -> None:
    names = list(by_backend)
    col = max(28, (term_width - 7) // 2)
    total = col * 2 + 3

    for idx in range(len(by_backend[names[0]])):
        left, right = by_backend[names[0]][idx], by_backend[names[1]][idx]
        print("=" * total)
        print(f"{left.id}  [{left.category}/{left.crop}]")
        print("-" * total)
        for line in _cell(left.prompt, total - 2):
            print(f"  {line}")
        print("-" * total)
        print(f"{names[0]:<{col}} | {names[1]:<{col}}")
        print("-" * col + "-+-" + "-" * col)

        lcell = [f"ERROR: {left.error}"] if left.error else _cell(left.output, col)
        rcell = [f"ERROR: {right.error}"] if right.error else _cell(right.output, col)
        for i in range(max(len(lcell), len(rcell))):
            l = lcell[i] if i < len(lcell) else ""
            r = rcell[i] if i < len(rcell) else ""
            print(f"{l:<{col}} | {r:<{col}}")

        print("-" * col + "-+-" + "-" * col)
        lstat = f"{left.latency_s:.2f}s  p={left.prompt_tokens} c={left.completion_tokens}"
        rstat = f"{right.latency_s:.2f}s  p={right.prompt_tokens} c={right.completion_tokens}"
        print(f"{lstat:<{col}} | {rstat:<{col}}")
    print("=" * total)


def print_summary(by_backend: dict[str, list[Result]]) -> None:
    print()
    print("SUMMARY")
    print(f"{'backend':<12} {'n':>3} {'ok':>3} {'median_s':>9} {'mean_s':>8} "
          f"{'prompt_tok':>11} {'completion_tok':>15}")
    for name, results in by_backend.items():
        ok = [r for r in results if not r.error]
        lat = sorted(r.latency_s for r in ok)
        median = lat[len(lat) // 2] if lat else 0.0
        mean = sum(lat) / len(lat) if lat else 0.0
        ptok = sum(r.prompt_tokens or 0 for r in ok)
        ctok = sum(r.completion_tokens or 0 for r in ok)
        print(f"{name:<12} {len(results):>3} {len(ok):>3} {median:>9.2f} {mean:>8.2f} "
              f"{ptok:>11} {ctok:>15}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--backend", default="local",
                        choices=["local", "cloudrun", "both"])
    parser.add_argument("--limit", type=int, default=None,
                        help="Run only the first N prompts.")
    args = parser.parse_args()

    taki_client.load_dotenv()
    rows = load_prompts(args.limit)
    backends = ["local", "cloudrun"] if args.backend == "both" else [args.backend]
    term_width = min(shutil.get_terminal_size((100, 24)).columns, 120)

    print(f"running {len(rows)} Hausa prompts against: {', '.join(backends)}")
    print(f"model comes from {PKG_ROOT / 'config' / 'models.yaml'}")
    if "cloudrun" in backends:
        print("NOTE: the cloudrun backend wakes a billable GPU instance.")
    print()

    by_backend: dict[str, list[Result]] = {}
    for backend in backends:
        results = []
        for i, row in enumerate(rows, 1):
            print(f"  [{backend}] {i}/{len(rows)} {row['id']} ...",
                  end="\r", file=sys.stderr, flush=True)
            results.append(run_one(row, backend))
        print(" " * 60, end="\r", file=sys.stderr)
        by_backend[backend] = results

    if len(backends) == 2:
        print_side_by_side(by_backend, term_width)
    else:
        print_single(by_backend[backends[0]], term_width)

    print_summary(by_backend)

    OUT_DIR.mkdir(exist_ok=True)
    out = OUT_DIR / f"results-{'-'.join(backends)}.json"
    out.write_text(json.dumps(
        {b: [asdict(r) for r in rs] for b, rs in by_backend.items()},
        ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\nfull results written to {out}")


if __name__ == "__main__":
    main()
