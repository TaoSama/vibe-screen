"""Create a machine-readable manifest for a verification evidence directory."""

from __future__ import annotations

import argparse
import json
import platform
import shlex
import subprocess
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Sequence

from . import SCHEMA_VERSION


class ManifestError(RuntimeError):
    """Raised when required provenance cannot be collected."""


def _run(command: Sequence[str], cwd: Path | None = None) -> str:
    try:
        result = subprocess.run(
            command,
            cwd=cwd,
            check=False,
            capture_output=True,
            text=True,
            timeout=15,
        )
    except (OSError, subprocess.TimeoutExpired) as error:
        raise ManifestError(f"failed to run {shlex.join(command)}: {error}") from error
    if result.returncode != 0:
        detail = result.stderr.strip() or result.stdout.strip() or "no output"
        raise ManifestError(
            f"{shlex.join(command)} exited with {result.returncode}: {detail}"
        )
    return result.stdout.strip()


def repository_state(repo: Path) -> dict[str, Any]:
    inside = _run(["git", "rev-parse", "--is-inside-work-tree"], repo)
    if inside != "true":
        raise ManifestError(f"not a Git work tree: {repo}")
    status = _run(["git", "status", "--porcelain=v1", "--untracked-files=all"], repo)
    try:
        revision_result = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=repo,
            check=False,
            capture_output=True,
            text=True,
            timeout=15,
        )
    except (OSError, subprocess.TimeoutExpired) as error:
        raise ManifestError(f"failed to inspect repository revision: {error}") from error
    revision = revision_result.stdout.strip() if revision_result.returncode == 0 else "UNBORN"
    return {
        "revision": revision,
        "dirty": bool(status),
        "status_porcelain": status.splitlines(),
    }


def build_manifest(
    *,
    kind: str,
    command: Sequence[str],
    repo: Path,
    notes: str | None = None,
    device: dict[str, Any] | None = None,
    measurement: dict[str, Any] | None = None,
) -> dict[str, Any]:
    manifest: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "run_id": str(uuid.uuid4()),
        "kind": kind,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "command": list(command),
        "repository": repository_state(repo.resolve()),
        "host": {
            "platform": platform.platform(),
            "python": platform.python_version(),
            "machine": platform.machine(),
        },
    }
    if notes:
        manifest["notes"] = notes
    if device is not None:
        manifest["device"] = device
    if measurement is not None:
        manifest["measurement"] = measurement
    return manifest


def write_manifest(path: Path, manifest: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    temporary.replace(path)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Create a Vibe Screen evidence manifest."
    )
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--kind", required=True, help="Evidence run kind, e.g. soak")
    parser.add_argument("--repo", type=Path, default=Path.cwd())
    parser.add_argument("--notes")
    parser.add_argument(
        "command",
        nargs=argparse.REMAINDER,
        help="Exact evidence command, placed after -- (optional)",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    command = args.command
    if command[:1] == ["--"]:
        command = command[1:]
    try:
        manifest = build_manifest(
            kind=args.kind,
            command=command,
            repo=args.repo,
            notes=args.notes,
        )
        write_manifest(args.output, manifest)
    except (ManifestError, OSError, ValueError) as error:
        print(f"error: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
