#!/usr/bin/env python3
"""Validate or record a Phase 3 public Internet soak evidence boundary.

The command does not substitute a local loopback soak for a public Internet run.
Without passing public preflight, remote TURN verifier, and a private two-hour
summary, it writes a blocked report when --allow-blocked is explicit.
"""

from __future__ import annotations

import argparse
from pathlib import Path
import sys
from typing import Sequence

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from scripts.phase3.public_internet_evidence import (  # noqa: E402
    BLOCKED_RESULT,
    PublicInternetEvidenceError,
    build_blocked_soak_report,
    build_soak_report,
    write_json,
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--preflight", type=Path)
    parser.add_argument("--verifier", type=Path)
    parser.add_argument("--private-summary", type=Path)
    parser.add_argument("--preset", choices=("30m", "2h", "8h"), default="2h")
    parser.add_argument("--blocked-reason", default="public Internet deployment prerequisites are not available")
    parser.add_argument("--allow-blocked", action="store_true")
    parser.add_argument("--output", type=Path, required=True)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        if args.preflight is None or args.verifier is None or args.private_summary is None:
            if not args.allow_blocked:
                missing = [
                    name
                    for name, value in (
                        ("--preflight", args.preflight),
                        ("--verifier", args.verifier),
                        ("--private-summary", args.private_summary),
                    )
                    if value is None
                ]
                raise PublicInternetEvidenceError(
                    "missing required public Internet soak input(s): " + ", ".join(missing)
                )
            report = build_blocked_soak_report(
                preflight_path=args.preflight,
                verifier_path=args.verifier,
                preset=args.preset,
                reason=args.blocked_reason,
            )
        else:
            report = build_soak_report(
                preflight_path=args.preflight,
                verifier_path=args.verifier,
                private_summary_path=args.private_summary,
                preset=args.preset,
            )
        write_json(args.output, report)
    except (OSError, PublicInternetEvidenceError) as error:
        print(f"error: {error}", file=sys.stderr)
        return 1
    if report["result"] == BLOCKED_RESULT:
        print(f"BLOCKED: public Internet soak evidence written to {args.output}")
        return 0 if args.allow_blocked else 2
    print(f"PASS: public Internet soak evidence written to {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
