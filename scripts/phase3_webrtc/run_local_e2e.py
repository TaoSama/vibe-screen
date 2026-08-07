#!/usr/bin/env python3
"""Run the local Phase 3 signaling and macOS libwebrtc E2E."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from scripts.phase3_webrtc.model import (  # noqa: E402
    DEFAULT_TIMEOUT_SECONDS,
    E2EFailure,
    SLICE_CONFIGURATION,
)
from scripts.phase3_webrtc.privacy import (  # noqa: E402
    project_and_validate_public_diagnostic,
    remove_private_diagnostics,
    remove_private_file,
    write_private_text,
)
from scripts.phase3_webrtc.session import (  # noqa: E402
    production_relay_hook_available,
    run_coturn_forced_relay,
    run_direct,
)
from scripts.phase3_webrtc.source_artifacts import (  # noqa: E402
    assert_evidence_matches_current_build,
    build_binaries,
    locate_binaries,
)


class ArgumentFailure(ValueError):
    """Command-line arguments were invalid without terminating the process."""


class FailClosedArgumentParser(argparse.ArgumentParser):
    def error(self, message: str) -> None:
        raise ArgumentFailure(message)


def argument_parser(*, add_help: bool = True) -> FailClosedArgumentParser:
    parser = FailClosedArgumentParser(
        description="Start real signaling and two macOS libwebrtc peers."
        if add_help
        else None,
        add_help=add_help,
        allow_abbrev=False,
    )
    parser.add_argument(
        "--mode",
        choices=("direct", "relay"),
        default="direct",
        help="Direct uses local ICE; relay additionally forces local coturn.",
    )
    parser.add_argument(
        "--slice",
        choices=tuple(SLICE_CONFIGURATION),
        default="transport",
        help="Transport runs channel smoke; product composes InternetProductSession.",
    )
    parser.add_argument(
        "--repo-root",
        type=Path,
        default=Path(__file__).resolve().parents[2],
        help="Repository root (default: inferred from this script).",
    )
    parser.add_argument(
        "--output",
        type=Path,
        help="Write private JSON evidence under <repo>/.build/.",
    )
    parser.add_argument(
        "--diagnostics-dir",
        type=Path,
        help="Write private diagnostic summaries under <repo>/.build/.",
    )
    parser.add_argument(
        "--skip-build",
        action="store_true",
        help="Use release binaries after validating the build manifest.",
    )
    parser.add_argument(
        "--timeout-seconds",
        type=int,
        default=DEFAULT_TIMEOUT_SECONDS,
        help=f"Per-process timeout (default: {DEFAULT_TIMEOUT_SECONDS}).",
    )
    parser.add_argument(
        "--turnserver",
        type=Path,
        default=Path(
            shutil.which("turnserver") or "/opt/homebrew/opt/coturn/bin/turnserver"
        ),
        help="coturn turnserver binary.",
    )
    return parser


def parse_arguments(arguments: list[str] | None = None) -> argparse.Namespace:
    parser = argument_parser()
    raw_arguments = list(sys.argv[1:] if arguments is None else arguments)
    for option in ("--repo-root", "--output", "--diagnostics-dir"):
        if _declared_option_count(raw_arguments, option) > 1:
            parser.error(f"{option} may be specified only once")
    parsed = parser.parse_args(raw_arguments)
    if parsed.timeout_seconds <= 0:
        parser.error("--timeout-seconds must be positive")
    return parsed


def validated_runner_path(
    repo_root: Path,
    configured_path: Path,
    label: str,
    *,
    allow_leaf_symlink: bool,
) -> Path:
    repo_root = repo_root.resolve()
    configured_allowed_root = repo_root / ".build"
    if configured_allowed_root.is_symlink():
        raise E2EFailure(f"{label} root must not be a symlink")
    allowed_root = configured_allowed_root.resolve(strict=False)
    configured_candidate = (
        configured_path
        if configured_path.is_absolute()
        else repo_root / configured_path
    )
    configured_candidate = Path(os.path.abspath(configured_candidate))
    candidate = (
        configured_candidate.parent.resolve(strict=False) / configured_candidate.name
    )
    try:
        relative = candidate.relative_to(allowed_root)
    except ValueError:
        raise E2EFailure(f"{label} must be inside <repo>/.build") from None
    if not relative.parts:
        raise E2EFailure(f"{label} must name a child of <repo>/.build")
    inspected = allowed_root
    components = relative.parts if not allow_leaf_symlink else relative.parts[:-1]
    for component in components:
        if inspected.is_symlink():
            raise E2EFailure(f"{label} path contains a symlink")
        if not inspected.exists():
            break
        inspected /= component
    if inspected.is_symlink():
        raise E2EFailure(f"{label} path contains a symlink")
    return candidate


def _declared_option_values(arguments: list[str], option: str) -> list[str]:
    values: list[str] = []
    index = 0
    while index < len(arguments):
        token = arguments[index]
        if token == option:
            if index + 1 < len(arguments) and not arguments[index + 1].startswith("--"):
                values.append(arguments[index + 1])
                index += 2
                continue
        elif token.startswith(option + "="):
            value = token.split("=", 1)[1]
            if value:
                values.append(value)
        index += 1
    return values


def _declared_option_count(arguments: list[str], option: str) -> int:
    return sum(
        token == option or token.startswith(option + "=") for token in arguments
    )


def preparse_declared_paths(arguments: list[str]) -> tuple[Path, list[Path], list[Path]]:
    repo_values = _declared_option_values(arguments, "--repo-root")
    repo_root = Path(repo_values[-1] if repo_values else Path(__file__).resolve().parents[2])
    outputs: list[Path] = []
    diagnostics: list[Path] = []
    for raw_output in _declared_option_values(arguments, "--output"):
        try:
            outputs.append(
                validated_runner_path(
                    repo_root,
                    Path(raw_output),
                    "evidence output",
                    allow_leaf_symlink=True,
                )
            )
        except (E2EFailure, OSError):
            continue
    for raw_diagnostics in _declared_option_values(arguments, "--diagnostics-dir"):
        try:
            diagnostics.append(
                validated_runner_path(
                    repo_root,
                    Path(raw_diagnostics),
                    "diagnostics directory",
                    allow_leaf_symlink=False,
                )
            )
        except (E2EFailure, OSError):
            continue
    return repo_root, outputs, diagnostics


def write_verified_evidence(
    repo_root: Path,
    path: Path | None,
    evidence: dict[str, object],
) -> None:
    """Write evidence only while it remains bound to the current build manifest."""
    if path is None:
        assert_evidence_matches_current_build(repo_root, evidence)
        json.dumps(evidence, indent=2, sort_keys=True)
        assert_evidence_matches_current_build(repo_root, evidence)
        print("Evidence record validated; no output path provided.")
        return
    completed = False
    try:
        remove_private_file(path)
        assert_evidence_matches_current_build(repo_root, evidence)
        rendered = json.dumps(evidence, indent=2, sort_keys=True) + "\n"
        write_private_text(path, rendered)
        assert_evidence_matches_current_build(repo_root, evidence)
        completed = True
    finally:
        if not completed:
            remove_private_file(path)
    print("Evidence record written.")


def print_success_summary(mode: str, slice_name: str) -> None:
    print(
        "Phase 3 local synthetic E2E: PASS "
        f"(mode={mode}, slice={slice_name})"
    )


def safe_failure_message(exception: BaseException, repo_root: Path) -> str:
    try:
        return project_and_validate_public_diagnostic(
            str(exception),
            private_paths=(repo_root, Path.home()),
        ).strip()
    except E2EFailure:
        return "diagnostic unavailable after privacy projection"


def remove_evidence_output(path: Path | None) -> None:
    """Remove a stale or failed evidence output without exposing its path."""
    if path is None:
        return
    remove_private_file(path)


def cleanup_declared_paths(outputs: list[Path], diagnostics: list[Path]) -> None:
    for path in outputs:
        remove_private_file(path)
    for directory in diagnostics:
        remove_private_diagnostics(directory)


def main(arguments: list[str] | None = None) -> int:
    raw_arguments = list(sys.argv[1:] if arguments is None else arguments)
    preparsed_repo, preparsed_outputs, preparsed_diagnostics = preparse_declared_paths(
        raw_arguments
    )
    repo_root = preparsed_repo
    output_path: Path | None = None
    diagnostics_dir: Path | None = None
    try:
        cleanup_declared_paths(preparsed_outputs, preparsed_diagnostics)
        arguments = parse_arguments(raw_arguments)
        repo_root = arguments.repo_root.resolve()
        if arguments.output is not None:
            output_path = validated_runner_path(
                repo_root,
                arguments.output,
                "evidence output",
                allow_leaf_symlink=True,
            )
        remove_evidence_output(output_path)
        diagnostics_dir = arguments.diagnostics_dir
        if diagnostics_dir is not None and not diagnostics_dir.is_absolute():
            diagnostics_dir = repo_root / diagnostics_dir
        if diagnostics_dir is not None:
            diagnostics_dir = validated_runner_path(
                repo_root,
                diagnostics_dir,
                "diagnostics directory",
                allow_leaf_symlink=False,
            )
            remove_private_diagnostics(diagnostics_dir)
        if arguments.skip_build:
            signaling_binary, mac_binary = locate_binaries(repo_root)
        else:
            signaling_binary, mac_binary, _ = build_binaries(
                repo_root, arguments.timeout_seconds
            )
        if arguments.mode == "direct":
            evidence = run_direct(
                repo_root,
                signaling_binary,
                mac_binary,
                arguments.timeout_seconds,
                slice_name=arguments.slice,
                diagnostics_dir=diagnostics_dir,
            )
            write_verified_evidence(repo_root, output_path, evidence)
            print_success_summary(arguments.mode, arguments.slice)
            return 0
        if not production_relay_hook_available(repo_root):
            raise E2EFailure("production forced-relay ICE is unavailable")
        coturn, peer_result = run_coturn_forced_relay(
            arguments,
            peer_test=lambda relay_environment: run_direct(
                repo_root,
                signaling_binary,
                mac_binary,
                arguments.timeout_seconds,
                mode="relay",
                slice_name=arguments.slice,
                peer_environment_overrides=relay_environment,
                diagnostics_dir=diagnostics_dir,
            ),
            diagnostics_dir=diagnostics_dir,
            repo_root=repo_root,
        )
        evidence = peer_result
        evidence["coturn"] = coturn
        write_verified_evidence(repo_root, output_path, evidence)
        print_success_summary(arguments.mode, arguments.slice)
        return 0
    except ArgumentFailure as exception:
        cleanup_error: Exception | None = None
        try:
            cleanup_declared_paths(preparsed_outputs, preparsed_diagnostics)
        except Exception as cleanup_exception:
            cleanup_error = cleanup_exception
        safe_error = safe_failure_message(cleanup_error or exception, repo_root)
        print(f"Phase 3 local WebRTC E2E: FAIL ({safe_error})", file=sys.stderr)
        return 2
    except Exception as exception:
        cleanup_error: Exception | None = None
        try:
            cleanup_declared_paths(
                [*preparsed_outputs, *([output_path] if output_path else [])],
                [
                    *preparsed_diagnostics,
                    *([diagnostics_dir] if diagnostics_dir else []),
                ],
            )
        except Exception as cleanup_exception:
            cleanup_error = cleanup_exception
        safe_error = safe_failure_message(cleanup_error or exception, repo_root)
        print(f"Phase 3 local WebRTC E2E: FAIL ({safe_error})", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
