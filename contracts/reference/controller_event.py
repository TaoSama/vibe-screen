from __future__ import annotations

from dataclasses import dataclass
import math
from typing import Mapping


MAXIMUM_ACTIVE_CONTROLLERS = 4
MAXIMUM_CONTROLLER_ID_BYTES = 128
DEFINED_BUTTON_MASK = 0b1_1111_1111_1111
MAXIMUM_ACTIVE_CONTROLLERS_REJECTION_REASON = "maximum_active_controllers_exceeded"

CONNECTED = 1
STATE = 2
DISCONNECTED = 3
VALID_KINDS = {CONNECTED, STATE, DISCONNECTED}


class ControllerEventValidationError(ValueError):
    """The event violates Protocol v1 controller semantics."""


@dataclass(frozen=True)
class ControllerEventResult:
    accepted: bool
    rejection_reason: str = ""


class ControllerEventValidator:
    """Reference lifecycle validator for one negotiated Protocol v1 session."""

    def __init__(self) -> None:
        self._last_input_id = 0
        self._active_epochs: dict[str, int] = {}
        self._last_epochs: dict[str, int] = {}

    def active_snapshot(self) -> tuple[tuple[str, int], ...]:
        return tuple(sorted(self._active_epochs.items()))

    def accept(self, event: Mapping[str, object]) -> ControllerEventResult:
        input_id = _required_int(event, "inputId")
        controller_id = _required_string(event, "controllerId")
        controller_epoch = _required_int(event, "controllerEpoch")
        kind = _required_int(event, "kindRawValue")

        _validate_scalar_fields(event, input_id, controller_id, controller_epoch, kind)
        if input_id <= self._last_input_id:
            if input_id == self._last_input_id:
                raise ControllerEventValidationError(
                    "input_id must not repeat in the session ControllerEvent stream"
                )
            raise ControllerEventValidationError(
                "input_id must strictly increase in the session ControllerEvent stream"
            )

        active_epoch = self._active_epochs.get(controller_id)
        if kind == CONNECTED:
            if active_epoch is not None:
                raise ControllerEventValidationError(
                    "an active lifecycle cannot be connected twice"
                )
            if controller_epoch <= self._last_epochs.get(controller_id, 0):
                raise ControllerEventValidationError(
                    "a new lifecycle must use an epoch greater than its prior epoch"
                )
            if len(self._active_epochs) >= MAXIMUM_ACTIVE_CONTROLLERS:
                self._last_input_id = input_id
                return ControllerEventResult(
                    accepted=False,
                    rejection_reason=MAXIMUM_ACTIVE_CONTROLLERS_REJECTION_REASON,
                )
            self._active_epochs[controller_id] = controller_epoch
            self._last_epochs[controller_id] = controller_epoch
        elif kind == STATE:
            if active_epoch != controller_epoch:
                raise ControllerEventValidationError(
                    "STATE requires an active matching lifecycle"
                )
        else:
            if active_epoch != controller_epoch:
                raise ControllerEventValidationError(
                    "DISCONNECTED requires an active matching lifecycle"
                )
            del self._active_epochs[controller_id]

        self._last_input_id = input_id
        return ControllerEventResult(accepted=True)


def _validate_scalar_fields(
    event: Mapping[str, object],
    input_id: int,
    controller_id: str,
    controller_epoch: int,
    kind: int,
) -> None:
    if input_id <= 0:
        raise ControllerEventValidationError("input_id must be non-zero")
    controller_id_bytes = len(controller_id.encode("utf-8"))
    if controller_id_bytes == 0:
        raise ControllerEventValidationError("controller_id must be non-empty")
    if controller_id_bytes > MAXIMUM_CONTROLLER_ID_BYTES:
        raise ControllerEventValidationError(
            "controller_id must encode to at most 128 UTF-8 bytes"
        )
    if controller_epoch <= 0:
        raise ControllerEventValidationError("controller_epoch must be non-zero")
    if kind not in VALID_KINDS:
        raise ControllerEventValidationError(
            "kind must be CONNECTED, STATE, or DISCONNECTED"
        )

    button_mask = _optional_int(event, "buttonMask")
    if button_mask < 0 or button_mask & ~DEFINED_BUTTON_MASK:
        raise ControllerEventValidationError("button bits 13-31 are reserved")

    sticks = tuple(
        _optional_number(event, key)
        for key in ("leftStickX", "leftStickY", "rightStickX", "rightStickY")
    )
    if not all(math.isfinite(value) and -1 <= value <= 1 for value in sticks):
        raise ControllerEventValidationError("stick axes must be finite and in [-1, 1]")

    triggers = tuple(
        _optional_number(event, key) for key in ("leftTrigger", "rightTrigger")
    )
    if not all(math.isfinite(value) and 0 <= value <= 1 for value in triggers):
        raise ControllerEventValidationError("triggers must be finite and in [0, 1]")

    hats = (_optional_int(event, "hatX"), _optional_int(event, "hatY"))
    if not all(value in {-1, 0, 1} for value in hats):
        raise ControllerEventValidationError("hat axes must each be -1, 0, or 1")

    if kind in {CONNECTED, DISCONNECTED} and (
        button_mask != 0
        or any(value != 0 for value in sticks)
        or any(value != 0 for value in triggers)
        or any(value != 0 for value in hats)
    ):
        name = "CONNECTED" if kind == CONNECTED else "DISCONNECTED"
        raise ControllerEventValidationError(f"{name} must be neutral")


def _required_int(event: Mapping[str, object], key: str) -> int:
    value = event.get(key)
    if not isinstance(value, int) or isinstance(value, bool):
        raise ControllerEventValidationError(f"{key} must be an integer")
    return value


def _required_string(event: Mapping[str, object], key: str) -> str:
    value = event.get(key)
    if not isinstance(value, str):
        raise ControllerEventValidationError(f"{key} must be a string")
    return value


def _optional_int(event: Mapping[str, object], key: str) -> int:
    value = event.get(key, 0)
    if not isinstance(value, int) or isinstance(value, bool):
        raise ControllerEventValidationError(f"{key} must be an integer")
    return value


def _optional_number(event: Mapping[str, object], key: str) -> float:
    value = event.get(key, 0)
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        raise ControllerEventValidationError(f"{key} must be a number")
    return float(value)
