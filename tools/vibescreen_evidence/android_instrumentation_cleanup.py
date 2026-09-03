"""Fail-safe cleanup for Android instrumentation test packages."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from typing import Callable


DEFAULT_TEST_PACKAGE = "dev.telemachus.display.test"
CLEANUP_SCHEMA = "dev.vibescreen.android-instrumentation-cleanup/v1"
EXPECTED_CLEANUP_COMMANDS = (
    ("force_stop_test_package", ("shell", "am", "force-stop", DEFAULT_TEST_PACKAGE)),
    ("uninstall_test_package", ("uninstall", DEFAULT_TEST_PACKAGE)),
    (
        "verify_test_package_absent",
        ("shell", "pm", "list", "packages", DEFAULT_TEST_PACKAGE),
    ),
)
EXPECTED_CLEANUP_SCOPE = {
    "target": "instrumentation_test_package",
    "product_package": "not_targeted",
    "product_data": "not_targeted",
    "adb_reverse": "not_targeted",
}
ABSENT_PACKAGE_MARKERS = (
    "delete_failed_internal_error",
    "not installed for",
    "unknown package",
    "not installed",
)


class InstrumentationCleanupError(RuntimeError):
    """Raised when the Android instrumentation test package could not be cleaned."""


@dataclass(frozen=True)
class CleanupCommandResult:
    name: str
    package_name: str
    command: tuple[str, ...]
    returncode: int
    stdout: str
    stderr: str

    @property
    def ok(self) -> bool:
        return self.returncode == 0 or _is_absent_package_result(self)

    @property
    def package_was_absent(self) -> bool:
        return _is_absent_package_result(self)


@dataclass(frozen=True)
class InstrumentationCleanupResult:
    schema: str
    package_name: str
    started_at_utc: str
    finished_at_utc: str
    force_stop_ok: bool
    uninstall_ok: bool
    package_absent_after_cleanup: bool
    cleanup_scope: dict[str, str]
    commands: tuple[CleanupCommandResult, ...]

    @property
    def ok(self) -> bool:
        return self.force_stop_ok and self.uninstall_ok and self.package_absent_after_cleanup

    def to_dict(self) -> dict[str, object]:
        data = asdict(self)
        data["commands"] = list(data["commands"])
        data["ok"] = self.ok
        return data


CleanupRunner = Callable[[str, str, tuple[str, ...]], CleanupCommandResult]


def cleanup_android_instrumentation_test_package(
    runner: CleanupRunner,
    *,
    test_package: str = DEFAULT_TEST_PACKAGE,
) -> InstrumentationCleanupResult:
    """Force-stop and uninstall only the Android instrumentation test package.

    The caller owns device authorization, serial selection, logging, and any
    surrounding app-specific teardown. This helper intentionally never touches
    the product package, product data, or ADB reverse mappings.
    """

    if not test_package.strip():
        raise ValueError("test_package must not be empty")
    if test_package != DEFAULT_TEST_PACKAGE:
        raise ValueError(f"test_package must be {DEFAULT_TEST_PACKAGE!r}")

    started = _utc_now()
    commands: list[CleanupCommandResult] = []

    force_stop = _run_cleanup_command(
        runner,
        "force_stop_test_package",
        test_package,
        ("shell", "am", "force-stop", test_package),
    )
    commands.append(force_stop)

    uninstall = _run_cleanup_command(
        runner,
        "uninstall_test_package",
        test_package,
        ("uninstall", test_package),
    )
    commands.append(uninstall)

    package_path = _run_cleanup_command(
        runner,
        "verify_test_package_absent",
        test_package,
        ("shell", "pm", "list", "packages", test_package),
    )
    commands.append(package_path)

    return InstrumentationCleanupResult(
        schema=CLEANUP_SCHEMA,
        package_name=test_package,
        started_at_utc=started,
        finished_at_utc=_utc_now(),
        force_stop_ok=force_stop.ok,
        uninstall_ok=uninstall.ok,
        package_absent_after_cleanup=_package_listing_is_absent(package_path),
        cleanup_scope=dict(EXPECTED_CLEANUP_SCOPE),
        commands=tuple(commands),
    )


def require_instrumentation_cleanup_ok(result: InstrumentationCleanupResult) -> None:
    errors = instrumentation_cleanup_result_errors(
        result.to_dict(),
        expected_package=result.package_name,
        field_prefix="instrumentation_cleanup",
    )
    if not errors:
        return
    failed = [command.name for command in result.commands if not command.ok]
    detail = ", ".join(failed) if failed else "; ".join(errors)
    raise InstrumentationCleanupError(
        f"Android instrumentation test package cleanup failed: {detail}"
    )


def instrumentation_cleanup_result_errors(
    cleanup: object,
    *,
    expected_package: str = DEFAULT_TEST_PACKAGE,
    field_prefix: str = "android_instrumentation_cleanup",
) -> list[str]:
    errors: list[str] = []
    if not isinstance(cleanup, dict):
        return [f"{field_prefix} must be an object: {type(cleanup).__name__}"]
    if cleanup.get("schema") != CLEANUP_SCHEMA:
        errors.append(f"{field_prefix}.schema mismatch: {cleanup.get('schema')!r}")
    if cleanup.get("ok") is not True:
        errors.append(f"{field_prefix}.ok is not verified true: {cleanup.get('ok')!r}")
    if cleanup.get("package_name") != expected_package:
        errors.append(f"{field_prefix}.package_name mismatch: {cleanup.get('package_name')!r}")
    for key in ("force_stop_ok", "uninstall_ok", "package_absent_after_cleanup"):
        if cleanup.get(key) is not True:
            errors.append(f"{field_prefix}.{key} is not verified true: {cleanup.get(key)!r}")
    if cleanup.get("cleanup_scope") != EXPECTED_CLEANUP_SCOPE:
        errors.append(f"{field_prefix}.cleanup_scope mismatch: {cleanup.get('cleanup_scope')!r}")
    expected_commands = _expected_cleanup_commands(expected_package)
    commands = cleanup.get("commands")
    if not isinstance(commands, list):
        errors.append(f"{field_prefix}.commands must be a list: {type(commands).__name__}")
        return errors
    if len(commands) != len(expected_commands):
        errors.append(f"{field_prefix}.commands count mismatch: {len(commands)}")
        return errors
    for index, (command, expected) in enumerate(zip(commands, expected_commands)):
        if not isinstance(command, dict):
            errors.append(f"{field_prefix}.commands[{index}] must be an object: {type(command).__name__}")
            continue
        expected_name, expected_arguments = expected
        if command.get("name") != expected_name:
            errors.append(f"{field_prefix}.commands[{index}].name mismatch: {command.get('name')!r}")
        if command.get("package_name") != expected_package:
            errors.append(
                f"{field_prefix}.commands[{index}].package_name mismatch: {command.get('package_name')!r}"
            )
        raw_command = command.get("command")
        if not isinstance(raw_command, (list, tuple)):
            errors.append(
                f"{field_prefix}.commands[{index}].command must be a list: {type(raw_command).__name__}"
            )
            continue
        if tuple(raw_command) != expected_arguments:
            errors.append(f"{field_prefix}.commands[{index}].command mismatch: {raw_command!r}")
        errors.extend(_cleanup_command_outcome_errors(command, index, field_prefix, expected_package))
    return errors


def _cleanup_command_outcome_errors(
    command: dict[str, object],
    index: int,
    field_prefix: str,
    expected_package: str,
) -> list[str]:
    prefix = f"{field_prefix}.commands[{index}]"
    errors: list[str] = []
    name = command.get("name")
    returncode = command.get("returncode")
    if type(returncode) is not int:
        return [f"{prefix}.returncode must be an int: {type(returncode).__name__}"]
    stdout = command.get("stdout")
    stderr = command.get("stderr")
    if not isinstance(stdout, str):
        errors.append(f"{prefix}.stdout must be a string: {type(stdout).__name__}")
        stdout = ""
    if not isinstance(stderr, str):
        errors.append(f"{prefix}.stderr must be a string: {type(stderr).__name__}")
        stderr = ""
    if errors:
        return errors

    if name == "force_stop_test_package" and returncode != 0:
        errors.append(f"{prefix}.returncode must be 0 for force-stop cleanup: {returncode!r}")
    elif name == "uninstall_test_package" and returncode != 0:
        output = f"{stdout}\n{stderr}".lower()
        if not any(marker in output for marker in ABSENT_PACKAGE_MARKERS):
            errors.append(
                f"{prefix}.returncode must be 0 or prove package absence for uninstall cleanup: {returncode!r}"
            )
    elif name == "verify_test_package_absent":
        if returncode != 0:
            errors.append(f"{prefix}.returncode must be 0 for package absence verification: {returncode!r}")
        expected_line = f"package:{expected_package}".lower()
        lines = [line.strip().lower() for line in stdout.splitlines()]
        if expected_line in lines:
            errors.append(f"{prefix}.stdout still lists {expected_package!r}")
    return errors


def _run_cleanup_command(
    runner: CleanupRunner,
    name: str,
    package_name: str,
    command: tuple[str, ...],
) -> CleanupCommandResult:
    try:
        return runner(name, package_name, command)
    except Exception as error:  # pragma: no cover - exercised through caller tests.
        return CleanupCommandResult(
            name=name,
            package_name=package_name,
            command=command,
            returncode=1,
            stdout="",
            stderr=str(error),
        )


def _expected_cleanup_commands(test_package: str) -> tuple[tuple[str, tuple[str, ...]], ...]:
    if test_package == DEFAULT_TEST_PACKAGE:
        return EXPECTED_CLEANUP_COMMANDS
    return tuple(
        (name, tuple(test_package if argument == DEFAULT_TEST_PACKAGE else argument for argument in command))
        for name, command in EXPECTED_CLEANUP_COMMANDS
    )


def _is_absent_package_result(result: CleanupCommandResult) -> bool:
    if result.name != "uninstall_test_package" or result.returncode == 0:
        return False
    output = f"{result.stdout}\n{result.stderr}".lower()
    return any(marker in output for marker in ABSENT_PACKAGE_MARKERS)


def _package_listing_is_absent(result: CleanupCommandResult) -> bool:
    if result.returncode != 0:
        return False
    expected_line = f"package:{result.package_name}".lower()
    lines = [line.strip().lower() for line in result.stdout.splitlines()]
    return expected_line not in lines


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()
