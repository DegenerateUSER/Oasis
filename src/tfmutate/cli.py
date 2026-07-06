"""Command-line entry point.

Two commands:
  * ``preview`` -- locate mutation targets and print each mutant as a unified diff (Phase 1).
  * ``run`` -- execute the full mutation cycle over a repo's test modules and write the CSV
    dataset (Phase 2): per module, init -> green-baseline gate -> per-mutant validate/test/
    classify, restoring git state after every cycle. Every SURVIVED mutant is additionally
    given a ``survival_reason`` by the Phase 4 classifier (PROJECT_SPEC.md §8).
"""

from __future__ import annotations

import argparse
import difflib
import logging
import os
import platform
import shlex
import shutil
import subprocess
import sys
import tempfile
import urllib.request
from collections import Counter
from pathlib import Path

from . import __version__, state
from .classifier import classify_outcomes
from .mutators import CATALOG, CATEGORIES, generate_mutants, select_operators
from .noop import read_tftest_files
from .parser import find_test_module_dirs, is_valid_hcl, read_tf_files

_GITHUB_REPO = "DegenerateUSER/Oasis"
_API_LATEST = f"https://api.github.com/repos/{_GITHUB_REPO}/releases/latest"
from .reporter import write_csv
from .runner import Runner, check_pinned_version


def _iter_targets(path: Path) -> list[Path]:
    if path.is_dir():
        return read_tf_files(path)
    return [path]


def _preview(args: argparse.Namespace) -> int:
    try:
        operators = select_operators(args.operator, args.category)
    except ValueError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    root = Path(args.target)
    if not root.exists():
        print(f"no such path: {root}", file=sys.stderr)
        return 2

    total = 0
    skipped = 0
    for tf in _iter_targets(root):
        text = tf.read_text()
        if not is_valid_hcl(text, args.fmt_cmd):
            skipped += 1  # genuine syntax error; logged by is_valid_hcl (SKIPPED_FILE)
            continue
        for mutant in generate_mutants(tf, text, operators):
            total += 1
            resource = mutant.resource_address or "(top-level)"
            print(
                f"\n[{mutant.operator_id}] {tf}:{mutant.line}  "
                f"[{mutant.surface}] {resource} .{mutant.attribute}"
            )
            arrow = "(deleted)" if mutant.is_deletion else repr(mutant.mutated_snippet)
            print(f"    {mutant.original_snippet!r} -> {arrow}")
            print(
                "".join(
                    difflib.unified_diff(
                        text.splitlines(keepends=True),
                        mutant.mutated_text.splitlines(keepends=True),
                        fromfile=f"{tf} (original)",
                        tofile=f"{tf} (mutant {mutant.operator_id})",
                        n=1,
                    )
                )
            )

    print(f"\n[+] {total} mutant(s) generated.")
    if skipped:
        print(f"[!] {skipped} file(s) skipped (failed `{args.fmt_cmd} fmt`; see warnings).")
    return 0


def _run(args: argparse.Namespace) -> int:
    root = Path(args.target)
    if not root.exists():
        print(f"no such path: {root}", file=sys.stderr)
        return 2
    root = root.resolve()  # absolute, so paths align with the git repo root

    binary = shlex.split(args.test_cmd)[0]
    try:
        repo_root = state.repo_root_of(root)
    except RuntimeError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    version = check_pinned_version(binary)
    print(f"[{'+' if version.ok else '!'}] {version.message}")
    if not version.ok and not args.allow_version_drift:
        print("Refusing to run on a version drift (pass --allow-version-drift to override).",
              file=sys.stderr)
        return 2

    try:
        operators = select_operators(args.operator, args.category)
    except ValueError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    module_dirs = find_test_module_dirs(root)
    if not module_dirs:
        print(f"no .tftest.hcl test modules found under {root}", file=sys.stderr)
        return 1
    print(f"[+] {len(module_dirs)} test module(s) under {root}")

    cache = Path(args.plugin_cache_dir).expanduser()
    cache.mkdir(parents=True, exist_ok=True)  # shared provider cache: offline, deterministic init

    all_outcomes = []
    for md in module_dirs:
        print(f"[+] {md.relative_to(repo_root)} ...", flush=True)
        runner = Runner(
            module_dir=md, repo_root=repo_root, test_cmd=args.test_cmd,
            timeout=args.timeout, operators=operators, plugin_cache_dir=cache,
        )
        outcomes = runner.run_module()
        classify_outcomes(outcomes, read_tftest_files(md))  # fills survival_reason (§8)
        all_outcomes.extend(outcomes)
        tally = Counter(o.test_status for o in outcomes)
        print("    " + ", ".join(f"{k}={v}" for k, v in sorted(tally.items())))

    n = write_csv(all_outcomes, args.output)
    scored = [o for o in all_outcomes if o.test_status in ("survived", "killed_assert", "killed_error")]
    killed = sum(o.test_status.startswith("killed") for o in scored)
    score = (killed / len(scored) * 100) if scored else 0.0
    print(f"\n[+] {n} row(s) -> {args.output}")
    print(f"[+] Mutation score: {score:.0f}% ({killed}/{len(scored)} killed; "
          f"no_op/invalid/baseline excluded).")

    survived = [o for o in all_outcomes if o.test_status == "survived"]
    if survived:
        reasons = Counter(o.survival_reason for o in survived)
        print(f"[+] Survived-mutant breakdown ({len(survived)} total): "
              + ", ".join(f"{k}={v}" for k, v in sorted(reasons.items())))

    if not state.is_clean(repo_root):
        print("[!] WARNING: git working tree is not clean after run.", file=sys.stderr)
        return 1
    return 0


def _add_operator_filters(subparser: argparse.ArgumentParser) -> None:
    """--operator (exact ID) and --category (one or more) are mutually exclusive filters,
    per PROJECT_SPEC.md §7: "each operator must be independently toggleable ... per category,
    not just overall"."""
    group = subparser.add_mutually_exclusive_group()
    group.add_argument(
        "-o", "--operator", help=f"limit to one operator (known: {', '.join(CATALOG)})"
    )
    group.add_argument(
        "-c", "--category", nargs="+", choices=CATEGORIES,
        help=f"limit to one or more categories (known: {', '.join(CATEGORIES)})",
    )


# ── Self-update ───────────────────────────────────────────────────────────────

def _detect_asset_name() -> tuple[str, str]:
    """Return (preferred_asset, fallback_tarball) for the current platform."""
    system = platform.system()   # Darwin / Linux / Windows
    machine = platform.machine() # arm64 / x86_64

    if system == "Darwin":
        return "oasis-macos-arm64.pkg", "oasis-darwin-arm64.tar.gz"
    if system == "Linux":
        return "oasis-linux-amd64.deb", "oasis-linux-amd64.tar.gz"
    # Windows — no installer package, just the zip
    return "", "oasis-windows-amd64.zip"


def _cmd_exists(cmd: str) -> bool:
    return shutil.which(cmd) is not None


def _update(args: argparse.Namespace) -> int:  # noqa: ARG001
    import json

    print(f"Oasis {__version__} — checking for updates...")

    try:
        req = urllib.request.Request(_API_LATEST, headers={"User-Agent": "oasis-updater"})
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read())
    except Exception as exc:  # noqa: BLE001
        print(f"\u274c Could not reach GitHub API: {exc}")
        return 1

    latest_tag: str = data.get("tag_name", "")          # e.g. "v1.2.0"
    latest_ver = latest_tag.lstrip("v")
    current_ver = __version__.lstrip("v")

    if latest_ver == current_ver:
        print(f"\u2705 Already up to date ({__version__}).")
        return 0

    print(f"New version available: {latest_tag}  (current: {__version__})")

    # Find download URLs from release assets
    assets: dict[str, str] = {
        a["name"]: a["browser_download_url"] for a in data.get("assets", [])
    }

    preferred, fallback = _detect_asset_name()
    system = platform.system()

    def download(url: str, suffix: str) -> str:
        """Stream-download url to a temp file, return its path."""
        tmp = tempfile.NamedTemporaryFile(delete=False, suffix=suffix)
        print(f"Downloading {url.split('/')[-1]}...")
        urllib.request.urlretrieve(url, tmp.name)  # noqa: S310
        return tmp.name

    # ── macOS .pkg ────────────────────────────────────────────────────────────
    if system == "Darwin" and preferred in assets:
        pkg = download(assets[preferred], ".pkg")
        print("Installing (you may be prompted for your password)...")
        result = subprocess.run(["sudo", "installer", "-pkg", pkg, "-target", "/"], check=False)
        os.unlink(pkg)
        if result.returncode != 0:
            print("\u274c installer failed. Try downloading manually from:")
            print(f"  https://github.com/{_GITHUB_REPO}/releases/latest")
            return 1
        print(f"\u2705 Updated to {latest_tag}! Restart your shell or run: rehash")
        return 0

    # ── Linux .deb ────────────────────────────────────────────────────────────
    if system == "Linux" and preferred in assets and _cmd_exists("dpkg"):
        deb = download(assets[preferred], ".deb")
        print("Installing (you may be prompted for your password)...")
        result = subprocess.run(["sudo", "dpkg", "-i", deb], check=False)
        os.unlink(deb)
        if result.returncode != 0:
            print("\u274c dpkg install failed. Try downloading manually from:")
            print(f"  https://github.com/{_GITHUB_REPO}/releases/latest")
            return 1
        print(f"\u2705 Updated to {latest_tag}!")
        return 0

    # ── Fallback: raw binary tarball / zip ────────────────────────────────────
    if fallback in assets:
        archive = download(assets[fallback], ".tar.gz" if fallback.endswith(".tar.gz") else ".zip")
        # Find installed binary location
        oasis_path = shutil.which("oasis") or "/usr/local/bin/oasis"
        with tempfile.TemporaryDirectory() as tmpdir:
            import tarfile, zipfile  # noqa: E401
            if fallback.endswith(".tar.gz"):
                with tarfile.open(archive) as t:
                    t.extractall(tmpdir)
                extracted = next(Path(tmpdir).iterdir())
            else:
                with zipfile.ZipFile(archive) as z:
                    z.extractall(tmpdir)
                extracted = next(Path(tmpdir).iterdir())
            extracted.chmod(0o755)
            result = subprocess.run(
                ["sudo", "mv", str(extracted), oasis_path], check=False
            )
        os.unlink(archive)
        if result.returncode != 0:
            print("\u274c Could not replace binary. Try running with sudo.")
            return 1
        print(f"\u2705 Updated to {latest_tag}!")
        return 0

    print("\u274c No compatible release asset found for this platform.")
    print(f"  Visit: https://github.com/{_GITHUB_REPO}/releases/latest")
    return 1


# ── Self-uninstall ────────────────────────────────────────────────────────────

def _uninstall(args: argparse.Namespace) -> int:
    oasis_path = shutil.which("oasis")

    if not oasis_path:
        print("\u274c Oasis binary not found in PATH.")
        print("   It may have already been removed or was installed outside your PATH.")
        return 1

    print(f"This will permanently remove Oasis from: {oasis_path}")

    if not getattr(args, "yes", False):
        try:
            confirm = input("Are you sure you want to uninstall Oasis? [y/N] ").strip().lower()
        except (EOFError, KeyboardInterrupt):
            print("\nAborted.")
            return 1
        if confirm not in ("y", "yes"):
            print("Aborted.")
            return 0

    system = platform.system()

    # On Debian/Ubuntu: prefer clean dpkg removal
    if system == "Linux" and _cmd_exists("dpkg"):
        probe = subprocess.run(
            ["dpkg", "-s", "oasis"], check=False, capture_output=True
        )
        if probe.returncode == 0:          # package is dpkg-managed
            print("Removing via dpkg (you may be prompted for your password)...")
            result = subprocess.run(["sudo", "dpkg", "-r", "oasis"], check=False)
            if result.returncode == 0:
                print("\u2705 Oasis uninstalled successfully.")
                return 0
            print("\u26a0\ufe0f  dpkg removal failed — falling back to direct file removal...")

    # macOS / Linux fallback: just delete the binary
    # (safe even while the binary is running on Unix — the inode persists until exit)
    print("Removing binary (you may be prompted for your password)...")
    result = subprocess.run(["sudo", "rm", "-f", oasis_path], check=False)
    if result.returncode == 0:
        print(f"\u2705 Oasis removed from {oasis_path}.")
        print("   Open a new terminal to clear the shell\'s command cache.")
        return 0

    print(f"\u274c Could not remove {oasis_path}.")
    print(f"   Try manually: sudo rm {oasis_path}")
    return 1


# ── Parser ────────────────────────────────────────────────────────────────────

def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="oasis", description=__doc__.splitlines()[0])
    parser.add_argument("-V", "--version", action="version", version=f"oasis {__version__}")
    sub = parser.add_subparsers(dest="command", required=True)

    preview = sub.add_parser("preview", help="show mutants for a .tf file or directory")
    preview.add_argument("target", help="a .tf file or a directory of .tf files")
    _add_operator_filters(preview)
    preview.add_argument(
        "--fmt-cmd", default="terraform",
        help="binary used to validate HCL (use 'tofu' for OpenTofu; default: terraform)",
    )
    preview.set_defaults(func=_preview)

    run = sub.add_parser("run", help="run the full mutation cycle over a repo and write a CSV")
    run.add_argument("target", help="a repo or directory containing .tftest.hcl test modules")
    run.add_argument("-O", "--output", default="results.csv", help="CSV output path")
    run.add_argument(
        "--test-cmd", default="terraform test",
        help="test command (use 'tofu test' for OpenTofu; default: 'terraform test')",
    )
    run.add_argument("--timeout", type=int, default=60, help="per-test timeout in seconds")
    _add_operator_filters(run)
    run.add_argument(
        "--plugin-cache-dir", default="~/.cache/tfmutate/plugins",
        help="shared provider plugin cache (offline, deterministic init across modules/runs)",
    )
    run.add_argument(
        "--allow-version-drift", action="store_true",
        help="proceed even if the test-cmd binary doesn't match its pinned version",
    )
    run.set_defaults(func=_run)

    update = sub.add_parser("update", help="download and install the latest Oasis release")
    update.set_defaults(func=_update)

    uninstall = sub.add_parser("uninstall", help="remove the Oasis binary from this system")
    uninstall.add_argument(
        "-y", "--yes", action="store_true",
        help="skip the confirmation prompt",
    )
    uninstall.set_defaults(func=_uninstall)

    return parser


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(level=logging.WARNING, format="[%(levelname)s] %(message)s")
    args = build_parser().parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
