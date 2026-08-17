from __future__ import annotations

import unittest

from contracts.reference.controller_event import (
    CONNECTED,
    DISCONNECTED,
    STATE,
    ControllerEventValidationError,
    ControllerEventValidator,
    MAXIMUM_ACTIVE_CONTROLLERS_REJECTION_REASON,
)


def event(
    input_id: int,
    controller_id: str,
    epoch: int,
    kind: int,
    **state: object,
) -> dict[str, object]:
    return {
        "inputId": input_id,
        "controllerId": controller_id,
        "controllerEpoch": epoch,
        "kindRawValue": kind,
        **state,
    }


class ControllerEventValidatorTest(unittest.TestCase):
    def test_valid_lifecycle_preserves_state_and_allows_greater_epoch(self) -> None:
        validator = ControllerEventValidator()

        self.assertTrue(validator.accept(event(1, "controller-1", 1, CONNECTED)).accepted)
        self.assertTrue(
            validator.accept(
                event(
                    2,
                    "controller-1",
                    1,
                    STATE,
                    buttonMask=1,
                    leftStickX=-1.0,
                    rightTrigger=1.0,
                    hatX=1,
                )
            ).accepted
        )
        self.assertEqual((("controller-1", 1),), validator.active_snapshot())
        self.assertTrue(validator.accept(event(3, "controller-1", 1, DISCONNECTED)).accepted)
        self.assertEqual((), validator.active_snapshot())
        self.assertTrue(validator.accept(event(4, "controller-1", 2, CONNECTED)).accepted)
        self.assertEqual((("controller-1", 2),), validator.active_snapshot())

    def test_state_and_disconnected_require_the_active_lifecycle_epoch(self) -> None:
        for kind, reason in (
            (STATE, "STATE requires an active matching lifecycle"),
            (DISCONNECTED, "DISCONNECTED requires an active matching lifecycle"),
        ):
            for mismatched_epoch in (1, 3):
                with self.subTest(kind=kind, mismatched_epoch=mismatched_epoch):
                    validator = ControllerEventValidator()
                    self.assertTrue(
                        validator.accept(event(1, "controller-1", 2, CONNECTED)).accepted
                    )

                    with self.assertRaisesRegex(ControllerEventValidationError, reason):
                        validator.accept(event(2, "controller-1", mismatched_epoch, kind))

                    self.assertEqual((("controller-1", 2),), validator.active_snapshot())

    def test_input_id_strictly_increases_across_interleaved_controllers(self) -> None:
        validator = ControllerEventValidator()
        self.assertTrue(validator.accept(event(1, "controller-1", 1, CONNECTED)).accepted)
        self.assertTrue(validator.accept(event(2, "controller-2", 1, CONNECTED)).accepted)
        self.assertTrue(validator.accept(event(4, "controller-1", 1, STATE)).accepted)

        with self.assertRaisesRegex(ControllerEventValidationError, "strictly increase"):
            validator.accept(event(3, "controller-2", 1, STATE))

        with self.assertRaisesRegex(ControllerEventValidationError, "must not repeat"):
            validator.accept(event(4, "controller-2", 1, STATE))

        self.assertTrue(validator.accept(event(5, "controller-2", 1, STATE)).accepted)

    def test_rejected_fifth_controller_consumes_input_id_and_can_retry_after_slot_opens(self) -> None:
        validator = ControllerEventValidator()
        for index in range(1, 5):
            self.assertTrue(
                validator.accept(event(index, f"controller-{index}", 1, CONNECTED)).accepted
            )

        admitted = validator.active_snapshot()
        rejection = validator.accept(event(5, "controller-5", 1, CONNECTED))
        self.assertFalse(rejection.accepted)
        self.assertEqual(
            MAXIMUM_ACTIVE_CONTROLLERS_REJECTION_REASON,
            rejection.rejection_reason,
        )
        self.assertEqual(admitted, validator.active_snapshot())

        with self.assertRaisesRegex(ControllerEventValidationError, "must not repeat"):
            validator.accept(event(5, "controller-1", 1, STATE))

        self.assertTrue(validator.accept(event(6, "controller-1", 1, DISCONNECTED)).accepted)
        self.assertTrue(validator.accept(event(7, "controller-5", 1, CONNECTED)).accepted)
        self.assertEqual(
            (
                ("controller-2", 1),
                ("controller-3", 1),
                ("controller-4", 1),
                ("controller-5", 1),
            ),
            validator.active_snapshot(),
        )


if __name__ == "__main__":
    unittest.main()
