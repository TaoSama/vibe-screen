from pathlib import Path
import unittest

from vibescreen_evidence.actionable_error_states import (
    _extract_balanced_brace_body,
    _find_next_open_brace,
)


REPO_ROOT = Path(__file__).resolve().parents[2]
SCREEN_CAPTURE = REPO_ROOT / "baseline/MacHost/Sources/ScreenCapture.swift"
CLEANUP_CALL = "clearStreamingResourcesAfterTerminalFailure"
CURRENT_MAIN_FALLBACK_ERROR = (
    "CGDisplayStream fallback is unavailable and ScreenCaptureKit did not "
    "produce a capture stream."
)


class ScreenCaptureLifecycleContractTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.source = SCREEN_CAPTURE.read_text(encoding="utf-8")

    def test_terminal_failure_cleanup_releases_encoder_and_cached_frame(self):
        cleanup = self._function_body("clearStreamingResourcesAfterTerminalFailure")

        self.assertIn("clearFramePacer()", cleanup)
        self.assertIn("invalidateFallbackCapture()", cleanup)
        self.assertIn("cgDisplayStream?.stop()", cleanup)
        self.assertIn("cgDisplayStream = nil", cleanup)
        self.assertIn("detachSCStreamForDeferredStop", cleanup)
        self.assertIn("encodedOutputMarkerLock.withLock", cleanup)
        self.assertIn("if releaseSessionResources", cleanup)
        session_release = self._window_after("if releaseSessionResources", source=cleanup)
        self.assertIn("isStopping = true", session_release)
        self.assertIn("restartTask?.cancel()", session_release)
        self.assertIn("streamStartTask?.cancel()", session_release)
        self.assertIn("replaceEncoder(nil)", session_release)
        self.assertIn("display = nil", session_release)
        self.assertIn("currentFrameSink = nil", session_release)
        self.assertIn("stopFrameMonitor()", cleanup)

    def test_terminal_report_is_single_fire_and_resets_on_fresh_session(self):
        report = self._function_body("reportTerminalCaptureFailure")
        claim = self._function_body("claimTerminalCaptureFailureReport")

        self.assertIn("guard claimTerminalCaptureFailureReport() else { return }", report)
        self.assertIn("terminalFailureReportLock.withLock", claim)
        self.assertIn("guard !reported else { return false }", claim)
        self.assertIn("reported = true", claim)
        self.assertIn(
            "terminalFailureReportLock.withLock { $0 = false }",
            self._function_body("resetTerminalCaptureFailureReport"),
        )
        self.assertIn("resetTerminalCaptureFailureReport()", self._function_body("startStreaming"))
        self.assertIn("resetTerminalCaptureFailureReport()", self._function_body("switchCapturedDisplay"))
        self.assertIn("resetTerminalCaptureFailureReport()", self._function_body("stopStreaming"))

    def test_start_streaming_cancels_prior_restart_before_new_session(self):
        startup = self._function_body("startStreaming")
        cancel = startup.find("restartTask?.cancel()")
        await_restart = startup.find("await restartTask?.value", cancel)
        clear = startup.find("restartTask = nil", await_restart)
        reset = startup.find("resetTerminalCaptureFailureReport()", clear)
        open_session = startup.find("isStopping = false", reset)
        current_sink = startup.find("currentFrameSink = frameSink", open_session)

        self.assertNotEqual(cancel, -1, "startStreaming must cancel a stale restart task")
        self.assertNotEqual(await_restart, -1, "startStreaming must wait for restart teardown")
        self.assertNotEqual(clear, -1, "startStreaming must clear the completed restart task")
        self.assertNotEqual(reset, -1, "startStreaming must reset terminal report after stale restart cleanup")
        self.assertNotEqual(open_session, -1, "startStreaming must reopen session state after stale restart cleanup")
        self.assertLess(clear, reset, "stale restart teardown must finish before terminal report reset")
        self.assertLess(reset, open_session, "terminal report reset must happen before new streaming state opens")
        self.assertLess(clear, current_sink, "restart teardown must finish before new session state is installed")

    def test_recoverable_switch_failure_preserves_frame_sink_for_rollback(self):
        marker = "Switch: SCStream setup/start failed"
        block = self._window_after(marker)

        self.assertIn("releaseSessionResources: reportsTerminalFailure", block)

    def test_terminal_cleanup_does_not_block_on_main_queue_sync(self):
        cleanup = self._function_body("clearStreamingResourcesAfterTerminalFailure")
        stop_monitor = self._function_body("stopFrameMonitor")

        self.assertIn("stopFrameMonitor()", cleanup)
        self.assertNotIn("DispatchQueue.main.sync", self.source)
        self.assertNotIn("stopFrameMonitorSafely", self.source)
        self.assertIn("frameMonitorTimerLock.withLock", stop_monitor)
        self.assertIn("currentTimer = nil", stop_monitor)

    def test_frame_monitor_installation_replaces_timer_under_lock(self):
        start_monitor = self._function_body("startFrameMonitor")

        self.assertIn("frameMonitorTimerLock.withLock", start_monitor)
        self.assertIn("currentTimer = timer", start_monitor)
        self.assertLess(
            start_monitor.find("currentTimer = timer"),
            start_monitor.find("timer.resume()"),
        )
        self.assertIn("replacedTimer?.cancel()", start_monitor)

    def test_terminal_cleanup_detaches_and_stops_scstream(self):
        detach = self._function_body("detachSCStreamForDeferredStop")

        self.assertIn("streamOutput?.onFrameReceived = nil", detach)
        self.assertIn("stream = nil", detach)
        self.assertIn("streamOutput = nil", detach)
        self.assertIn("streamDelegate = nil", detach)
        self.assertIn("streamStopBarrier.enqueue", detach)
        self.assertIn("try await streamToStop.stopCapture()", detach)
        self.assertIn("detachSCStreamForDeferredStop", self._function_body("attemptFallbackCapture"))
        self.assertIn("detachSCStreamForDeferredStop", self._function_body("clearStreamingResourcesAfterTerminalFailure"))

    def test_stop_streaming_uses_deferred_scstream_stop(self):
        stop = self._function_body("stopStreaming")
        detach = stop.find("detachSCStreamForDeferredStop")
        wait_after_detach = stop.find("await streamStopBarrier.waitForAll()", detach)

        self.assertNotEqual(detach, -1, "stopStreaming must detach and stop any SCStream")
        self.assertNotEqual(
            wait_after_detach,
            -1,
            "stopStreaming must wait for the deferred SCStream stop to finish",
        )

    def test_start_switch_and_restart_terminal_failures_use_cleanup(self):
        for marker in (
            "Switch: SCStream setup/start failed",
            "Failed to start SCStream capture",
            "SCStream restart failed",
        ):
            with self.subTest(marker=marker):
                self.assertIn(
                    CLEANUP_CALL,
                    self._window_after(marker),
                )

    def test_terminal_reports_clear_resources_before_reporting_failure(self):
        search_start = 0
        while True:
            report = self.source.find("reportTerminalCaptureFailure", search_start)
            if report == -1:
                break
            search_start = report + len("reportTerminalCaptureFailure")
            if "private func reportTerminalCaptureFailure" in self.source[report - 20:report + 40]:
                continue
            with self.subTest(report_offset=report):
                cleanup_window = self.source[max(0, report - 500):report]
                self.assertIn(
                    CLEANUP_CALL,
                    cleanup_window,
                    "terminal reports must synchronously clear retained capture resources first",
                )

    def test_current_main_fallback_unavailable_clears_before_throwing(self):
        marker = CURRENT_MAIN_FALLBACK_ERROR
        marker_index = self.source.find(marker)
        self.assertNotEqual(marker_index, -1, "missing current-main fallback error")
        cleanup = self.source.rfind(CLEANUP_CALL, 0, marker_index)
        thrown = self.source.rfind("throw NSError", 0, marker_index)
        self.assertNotEqual(cleanup, -1, "missing cleanup before current-main fallback throw")
        self.assertNotEqual(thrown, -1, "missing current-main fallback throw")
        self.assertLess(cleanup, thrown, "cleanup must precede current-main fallback throw")

    def test_code_11_startup_and_restart_errors_reach_cleanup_catch(self):
        startup = self._function_body("startStreaming")
        startup_error = startup.find('"Capture stream was not configured."')
        startup_catch = startup.find("} catch {", startup_error)
        startup_cleanup = startup.find(CLEANUP_CALL, startup_catch)
        self.assertNotEqual(startup_error, -1, "missing startup code 11 error")
        self.assertNotEqual(startup_catch, -1, "startup code 11 must be inside the cleanup catch")
        self.assertNotEqual(startup_cleanup, -1, "startup code 11 catch must clean resources")

        restart = self._function_body("restartStream")
        restart_error = restart.find('"Restarted capture stream was not configured."')
        restart_catch = restart.find("} catch {", restart_error)
        restart_cleanup = restart.find(CLEANUP_CALL, restart_catch)
        self.assertNotEqual(restart_error, -1, "missing restart code 11 error")
        self.assertNotEqual(restart_catch, -1, "restart code 11 must be inside the cleanup catch")
        self.assertNotEqual(restart_cleanup, -1, "restart code 11 catch must clean resources")

    def test_start_tasks_do_not_mark_started_after_terminal_stop(self):
        for function_name in ("switchCapturedDisplay", "startStreaming", "restartStream"):
            with self.subTest(function=function_name):
                function = self._function_body(function_name)
                assignment = function.find("self.isSCStreamStarted = true")
                self.assertNotEqual(assignment, -1)
                window = function[max(0, assignment - 200):assignment]
                self.assertIn("Task.checkCancellation()", window)
                self.assertIn("guard !self.isStopping", window)

    def test_restart_stop_guards_enter_cancellation_cleanup(self):
        restart = self._function_body("restartStream")
        cancellation_catch = restart.find("} catch is CancellationError {")
        self.assertNotEqual(cancellation_catch, -1, "restart cancellation catch missing")
        restart_do_body = restart[:cancellation_catch]

        self.assertNotIn("guard !self.isStopping else { return }", restart_do_body)
        self.assertGreaterEqual(
            restart_do_body.count("guard !self.isStopping else { throw CancellationError() }"),
            5,
        )
        self.assertIn(
            CLEANUP_CALL,
            restart[cancellation_catch:restart.find("} catch {", cancellation_catch)],
        )

    def test_restart_supersede_cancellation_detaches_capture_without_terminal_release(self):
        restart = self._function_body("restartStream")
        superseded = restart.find('debugLog("SCStream restart superseded")')
        generic_catch = restart.find("} catch {", superseded)
        self.assertNotEqual(superseded, -1, "restart supersede branch missing")
        self.assertNotEqual(generic_catch, -1, "restart generic catch missing")

        superseded_body = restart[superseded:generic_catch]
        self.assertIn(
            "clearStreamingResourcesAfterTerminalFailure(",
            superseded_body,
        )
        self.assertIn(
            "releaseSessionResources: false",
            superseded_body,
        )

    def test_start_streaming_cancellation_clears_start_task_reference(self):
        startup = self._function_body("startStreaming")
        cancellation_catch = startup.find("} catch is CancellationError where isStopping {")
        self.assertNotEqual(cancellation_catch, -1, "missing startStreaming cancellation catch")
        cancellation_body = startup[cancellation_catch:startup.find("} catch {", cancellation_catch)]

        self.assertIn("streamStartTask = nil", cancellation_body)
        self.assertIn("throw CancellationError()", cancellation_body)

    def _function_body(self, name: str) -> str:
        marker = f"func {name}"
        start = self.source.find(marker)
        self.assertNotEqual(start, -1, f"missing {name}")
        body_start = _find_next_open_brace(self.source, start + len(marker))
        self.assertNotEqual(body_start, -1, f"missing body for {name}")
        return self.source[start:body_start] + "{" + _extract_balanced_brace_body(
            self.source,
            body_start,
        ) + "}"

    def _window_after(self, marker: str, length: int = 800, source: str | None = None) -> str:
        text = source if source is not None else self.source
        start = text.find(marker)
        self.assertNotEqual(start, -1, f"missing marker {marker}")
        return text[start:start + length]


if __name__ == "__main__":
    unittest.main()
