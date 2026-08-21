#!/usr/bin/env python3
"""Verify a real remote TURN allocation through the Phase 3 relay control plane."""

from __future__ import annotations

import argparse
from pathlib import Path
import sys
from typing import Sequence

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from scripts.phase3.public_internet_evidence import (  # noqa: E402
    PublicInternetEvidenceError,
    build_verifier_report,
    write_json,
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--preflight", type=Path, required=True)
    parser.add_argument("--relay-url", required=True)
    parser.add_argument("--client-token-file", type=Path, required=True)
    parser.add_argument("--device-id", required=True)
    parser.add_argument("--session-id", required=True)
    parser.add_argument("--allocation-id", required=True)
    parser.add_argument("--peer-host", required=True)
    parser.add_argument("--peer-port", required=True, type=int)
    parser.add_argument("--turnutils-uclient", default="turnutils_uclient")
    parser.add_argument("--timeout-seconds", type=float, default=10.0)
    parser.add_argument("--messages", type=int, default=5)
    parser.add_argument("--output", type=Path, required=True)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.timeout_seconds <= 0 or args.messages <= 0:
        print("error: timeouts and message count must be positive", file=sys.stderr)
        return 2
    try:
        report = build_verifier_report(
            preflight_path=args.preflight,
            relay_url=args.relay_url,
            client_token_file=args.client_token_file,
            device_id=args.device_id,
            session_id=args.session_id,
            allocation_id=args.allocation_id,
            peer_host=args.peer_host,
            peer_port=args.peer_port,
            turnutils_uclient=args.turnutils_uclient,
            timeout_seconds=args.timeout_seconds,
            messages=args.messages,
        )
        write_json(args.output, report)
    except (OSError, PublicInternetEvidenceError) as error:
        print(f"error: {error}", file=sys.stderr)
        return 1
    print(f"PASS: remote TURN verifier evidence written to {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
