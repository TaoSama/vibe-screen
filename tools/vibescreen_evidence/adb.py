"""Small, dependency-free ADB boundary for device evidence collection."""

from __future__ import annotations

from dataclasses import dataclass
import re
import subprocess
from typing import Any, Callable, Sequence


CommandRunner = Callable[..., subprocess.CompletedProcess[str]]


# Optional power_supply sysfs diagnostics. Devices may deny read permission or
# omit these nodes entirely; that is treated as an unavailable value, not an
# evidence-collection failure.
_POWER_SUPPLY_NODES = {
    "current_now_ua": "/sys/class/power_supply/battery/current_now",
    "current_average_ua": "/sys/class/power_supply/battery/current_avg",
    "charge_counter_uah": "/sys/class/power_supply/battery/charge_counter",
    "voltage_now_uv": "/sys/class/power_supply/battery/voltage_now",
}

_POWER_NODE_UNAVAILABLE_PATTERN = re.compile(
    r"(^|\n)cat: |permission denied|no such file or directory|not a directory|"
    r"is a directory|i/o error|operation not permitted"
)


class ADBError(RuntimeError):
    """Raised when an ADB command cannot produce trustworthy evidence."""


@dataclass(frozen=True)
class ADBResult:
    stdout: str
    stderr: str


class ADBClient:
    """Runs ADB commands against one explicit serial."""

    def __init__(
        self,
        serial: str,
        *,
        adb_path: str = "adb",
        timeout_seconds: float = 15.0,
        command_runner: CommandRunner = subprocess.run,
    ) -> None:
        if not serial.strip():
            raise ValueError("ADB serial must not be empty")
        if timeout_seconds <= 0:
            raise ValueError("ADB timeout must be positive")
        self.serial = serial
        self.adb_path = adb_path
        self.timeout_seconds = timeout_seconds
        self._command_runner = command_runner

    def _invoke(
        self, arguments: Sequence[str], *, device: bool
    ) -> subprocess.CompletedProcess[str]:
        """Run one ADB command, converting transport faults to ADBError.

        A non-zero exit is returned to the caller rather than raised so that
        callers reading optional device nodes can distinguish an unavailable
        node from a broken ADB transport. Timeouts, a missing executable, and
        other OS-level launch failures always surface as ADBError.
        """
        command = [self.adb_path]
        if device:
            command.extend(("-s", self.serial))
        command.extend(arguments)
        try:
            return self._command_runner(
                command,
                check=False,
                capture_output=True,
                text=True,
                timeout=self.timeout_seconds,
            )
        except FileNotFoundError as error:
            raise ADBError(f"ADB executable not found: {self.adb_path}") from error
        except subprocess.TimeoutExpired as error:
            raise ADBError(
                f"ADB command timed out after {self.timeout_seconds:g}s: "
                f"{' '.join(command)}"
            ) from error
        except OSError as error:
            raise ADBError(f"ADB command could not start: {error}") from error

    def _run(self, arguments: Sequence[str], *, device: bool = True) -> ADBResult:
        completed = self._invoke(arguments, device=device)
        if completed.returncode != 0:
            command = [self.adb_path]
            if device:
                command.extend(("-s", self.serial))
            command.extend(arguments)
            detail = completed.stderr.strip() or completed.stdout.strip() or "no output"
            raise ADBError(
                f"ADB command failed ({completed.returncode}): {' '.join(command)}: {detail}"
            )
        return ADBResult(completed.stdout.strip(), completed.stderr.strip())

    def adb_version(self) -> str:
        return self._run(("version",), device=False).stdout

    def connect(self) -> str:
        if not _is_tcp_endpoint(self.serial):
            # USB-attached serials are not valid "adb connect" targets; the
            # device is already present, so only verify that it is ready.
            self.require_device()
            return f"already connected to {self.serial}"
        result = self._run(("connect", self.serial), device=False).stdout
        normalized = result.lower()
        if "connected to" not in normalized and "already connected" not in normalized:
            raise ADBError(f"ADB did not confirm connection to {self.serial}: {result}")
        self.require_device()
        return result

    def require_device(self) -> None:
        state = self._run(("get-state",)).stdout
        if state != "device":
            raise ADBError(f"ADB target {self.serial} is not ready (state={state!r})")

    def shell(self, *arguments: str) -> str:
        return self._run(("shell", *arguments)).stdout

    def identity(self) -> dict[str, Any]:
        properties = {
            "manufacturer": "ro.product.manufacturer",
            "model": "ro.product.model",
            "device": "ro.product.device",
            "product": "ro.product.name",
            "android_release": "ro.build.version.release",
            "sdk": "ro.build.version.sdk",
            "build_fingerprint": "ro.build.fingerprint",
            "abi": "ro.product.cpu.abi",
        }
        identity: dict[str, Any] = {"adb_serial": self.serial}
        for name, property_name in properties.items():
            value = self.shell("getprop", property_name)
            identity[name] = int(value) if name == "sdk" and value.isdigit() else value
        identity["device_serial"] = self.shell("getprop", "ro.serialno")
        return identity

    def sample(self, package_name: str | None = None) -> dict[str, Any]:
        errors: list[str] = []
        device: dict[str, Any] = {}
        device["process"] = self._collect_process(package_name, errors)
        device["memory"] = self._collect_memory(package_name, errors)
        device["thermal"] = self._collect_thermal(errors)
        device["battery"] = self._collect_battery(errors)
        device["power"] = self._collect_power(errors)
        return {"device": device, "errors": errors}

    def _safe_shell(
        self, metric: str, errors: list[str], *arguments: str
    ) -> str | None:
        try:
            return self.shell(*arguments)
        except ADBError as error:
            errors.append(f"{metric}: {error}")
            return None

    def _collect_process(
        self, package_name: str | None, errors: list[str]
    ) -> dict[str, Any]:
        if package_name is None:
            return {"package": None, "running": None, "pids": []}
        output = self._safe_shell("process", errors, "ps", "-A", "-o", "PID,NAME")
        pids = []
        for line in (output or "").splitlines():
            fields = line.split()
            if len(fields) >= 2 and fields[0].isdigit():
                process_name = fields[-1]
                if process_name == package_name or process_name.startswith(f"{package_name}:"):
                    pids.append(int(fields[0]))
        return {"package": package_name, "running": bool(pids), "pids": pids}

    def _collect_memory(
        self, package_name: str | None, errors: list[str]
    ) -> dict[str, Any]:
        output = self._safe_shell("memory.system", errors, "cat", "/proc/meminfo")
        memory: dict[str, Any] = {"system_kb": _parse_meminfo(output or "")}
        if package_name is not None:
            app_output = self._safe_shell(
                "memory.app", errors, "dumpsys", "meminfo", package_name
            )
            memory["app_total_pss_kb"] = _parse_total_pss(app_output or "")
        return memory

    def _collect_thermal(self, errors: list[str]) -> dict[str, Any]:
        output = self._safe_shell("thermal", errors, "dumpsys", "thermalservice")
        return _parse_thermal(output or "")

    def _collect_battery(self, errors: list[str]) -> dict[str, Any]:
        output = self._safe_shell("battery", errors, "dumpsys", "battery")
        return _parse_key_values(output or "")

    def _collect_power(self, errors: list[str]) -> dict[str, int | None]:
        values: dict[str, int | None] = {}
        for name, path in _POWER_SUPPLY_NODES.items():
            values[name] = self._read_power_node(f"power.{name}", path, errors)
        return values

    def _read_power_node(
        self, metric: str, path: str, errors: list[str]
    ) -> int | None:
        """Read one power_supply sysfs node.

        These nodes are optional diagnostics: on some devices the ADB shell
        user lacks permission to read them or the node does not exist. Those
        outcomes are recorded as an unavailable value (None) without an error.
        A broken ADB transport (timeout, offline, unauthorized, missing
        executable) is still recorded as an error.
        """
        try:
            completed = self._invoke(("shell", "cat", path), device=True)
        except ADBError as error:
            errors.append(f"{metric}: {error}")
            return None
        if completed.returncode != 0:
            message = (completed.stderr or completed.stdout or "").lower()
            if _POWER_NODE_UNAVAILABLE_PATTERN.search(message):
                return None
            detail = completed.stderr.strip() or completed.stdout.strip() or "no output"
            errors.append(
                f"{metric}: ADB command failed ({completed.returncode}): "
                f"cat {path}: {detail}"
            )
            return None
        output = completed.stdout.strip()
        return int(output) if re.fullmatch(r"-?\d+", output) else None


def _is_tcp_endpoint(serial: str) -> bool:
    """Return True when the serial is an adb connect host:port target."""
    return bool(re.fullmatch(r"[^\s]+:\d{1,5}", serial.strip()))


def _parse_meminfo(output: str) -> dict[str, int]:
    values: dict[str, int] = {}
    for line in output.splitlines():
        match = re.fullmatch(r"([A-Za-z0-9_()]+):\s+(\d+)\s+kB", line.strip())
        if match:
            values[match.group(1)] = int(match.group(2))
    return values


def _parse_total_pss(output: str) -> int | None:
    for pattern in (r"TOTAL PSS:\s*(\d+)", r"^\s*TOTAL\s+(\d+)\s"):
        match = re.search(pattern, output, flags=re.MULTILINE)
        if match:
            return int(match.group(1))
    return None


def _parse_key_values(output: str) -> dict[str, Any]:
    values: dict[str, Any] = {}
    for line in output.splitlines():
        if ":" not in line:
            continue
        key, raw_value = (part.strip() for part in line.split(":", 1))
        if not key:
            continue
        if re.fullmatch(r"-?\d+", raw_value):
            value: Any = int(raw_value)
        elif raw_value.lower() in ("true", "false"):
            value = raw_value.lower() == "true"
        else:
            value = raw_value
        values[key.replace(" ", "_")] = value
    return values


def _parse_thermal(output: str) -> dict[str, Any]:
    status_match = re.search(r"Thermal Status:\s*(\d+)", output)
    temperatures = []
    pattern = re.compile(
        r"Temperature\{mValue=([-+]?\d+(?:\.\d+)?), mType=(\d+), "
        r"mName=([^,}]+), mStatus=(\d+)"
    )
    for match in pattern.finditer(output):
        temperatures.append(
            {
                "celsius": float(match.group(1)),
                "type": int(match.group(2)),
                "name": match.group(3),
                "status": int(match.group(4)),
            }
        )
    return {
        "status": int(status_match.group(1)) if status_match else None,
        "temperatures": temperatures,
    }
