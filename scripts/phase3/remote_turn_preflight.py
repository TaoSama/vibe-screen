#!/usr/bin/env python3
"""Preflight a Phase 3 public Internet remote TURN deployment.

The command writes a structured report for every run. Missing production
deployment state is a BLOCKED result, not a local fallback and not pass evidence.
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
    build_preflight_report,
    write_json,
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--relay-config",
        type=Path,
        default=Path("deploy/phase3/config/relay.production.json"),
        help="Git-ignored production relay config, not the checked-in example file.",
    )
    parser.add_argument(
        "--coturn-config",
        type=Path,
        default=Path("deploy/phase3/coturn/production.conf"),
    )
    parser.add_argument("--turn-secret-file", type=Path)
    parser.add_argument("--tls-certificate", type=Path)
    parser.add_argument("--tls-private-key", type=Path)
    parser.add_argument("--coturn-external-ip")
    parser.add_argument("--authority-ready-url")
    parser.add_argument("--relay-ready-url")
    parser.add_argument("--timeout-seconds", type=float, default=10.0)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument(
        "--allow-blocked",
        action="store_true",
        help="Return zero after writing blocked evidence for environments without public deployment prerequisites.",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.timeout_seconds <= 0:
        print("error: --timeout-seconds must be positive", file=sys.stderr)
        return 2
    try:
        report = build_preflight_report(
            relay_config_path=args.relay_config,
            coturn_config_path=args.coturn_config,
            turn_secret_file=args.turn_secret_file,
            tls_certificate=args.tls_certificate,
            tls_private_key=args.tls_private_key,
            coturn_external_ip=args.coturn_external_ip,
            authority_ready_url=args.authority_ready_url,
            relay_ready_url=args.relay_ready_url,
            timeout_seconds=args.timeout_seconds,
        )
        write_json(args.output, report)
    except (OSError, PublicInternetEvidenceError) as error:
        print(f"error: {error}", file=sys.stderr)
        return 1
    if report["result"] == BLOCKED_RESULT:
        print(f"BLOCKED: public Internet preflight evidence written to {args.output}")
        return 0 if args.allow_blocked else 2
    print(f"PASS: public Internet preflight evidence written to {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
