"""Run the fast suite with a hard <=120 second process-tree budget.

No benchmark corpus is executed. Provider-download tests remain opt-in via plain
pytest, not this helper. Optional paths restrict the feedback loop further.
"""
from __future__ import annotations

import argparse
import os
from pathlib import Path
import signal
import subprocess
import sys
import time


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("paths", nargs="*", default=["tests"])
    parser.add_argument("--seconds", type=float, default=120)
    parser.add_argument("--log", type=Path)
    args = parser.parse_args(argv)
    if not 0 < args.seconds <= 120:
        parser.error("--seconds must be greater than zero and at most 120")
    root = Path(__file__).resolve().parents[1]
    env = dict(os.environ)
    scratch = Path(env.get("TMPDIR", str(Path.home() / ".cache" / "oasis" / "test-tmp")))
    scratch.mkdir(parents=True, exist_ok=True)
    env["TMPDIR"] = str(scratch)
    command = [sys.executable, "-m", "pytest", "-q", *args.paths]
    started = time.perf_counter()
    process = subprocess.Popen(command, cwd=root, env=env, stdout=subprocess.PIPE,
                               stderr=subprocess.STDOUT, text=True,
                               start_new_session=(os.name == "posix"))
    try:
        output, _ = process.communicate(timeout=args.seconds)
        code = process.returncode
    except subprocess.TimeoutExpired:
        if os.name == "posix":
            os.killpg(process.pid, signal.SIGKILL)
        else:
            process.kill()
        output, _ = process.communicate()
        output += f"\nFAILED: hard {args.seconds:g}s budget exhausted; no corpus was run.\n"
        code = 124
    output += f"\nQuick-check wall time: {time.perf_counter() - started:.2f}s\n"
    print(output, end="")
    if args.log:
        args.log.parent.mkdir(parents=True, exist_ok=True)
        args.log.write_text(output)
    return code


if __name__ == "__main__":
    raise SystemExit(main())
