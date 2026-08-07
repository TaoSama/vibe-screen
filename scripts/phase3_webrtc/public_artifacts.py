#!/usr/bin/env python3
"""Validate the exact public artifact set before CI upload."""

from __future__ import annotations

import argparse
from pathlib import Path
import sys

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from scripts.phase3_webrtc.model import E2EFailure  # noqa: E402
from scripts.phase3_webrtc.public_evidence import (  # noqa: E402
    build_gate_failure_diagnostic,
    build_public_artifact_tree,
)


def parse_arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Fail closed unless Phase 3 CI artifacts are public-safe JSON."
    )
    parser.add_argument(
        "--root",
        type=Path,
        required=True,
        help="Private runner output root. This directory is never uploaded.",
    )
    parser.add_argument(
        "--output",
        type=Path,
        help="Public projection directory (default: <root>/public).",
    )
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--allow-missing", action="store_true")
    mode.add_argument(
        "--failure-diagnostic",
        action="store_true",
        help="Write a fixed gate-failure marker without projecting evidence.",
    )
    return parser.parse_args()


def main() -> int:
    arguments = parse_arguments()
    default_output = "public-failure" if arguments.failure_diagnostic else "public"
    output = arguments.output or arguments.root / default_output
    try:
        if arguments.failure_diagnostic:
            checked = build_gate_failure_diagnostic(arguments.root, output)
        else:
            checked = build_public_artifact_tree(
                arguments.root,
                output,
                allow_missing=arguments.allow_missing,
            )
    except E2EFailure as exception:
        print(f"Phase 3 public artifact validation: FAIL ({exception})", file=sys.stderr)
        return 1
    if arguments.failure_diagnostic:
        print(f"Phase 3 gate failure diagnostic written ({checked} file)")
    else:
        print(f"Phase 3 public artifact projection: PASS ({checked} files)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
