# Interrupted 30-minute attempt

This directory preserves an intentionally interrupted run from 2026-08-10.
The run stopped after 14 samples (about seven minutes) when code review found a
cross-session video-configuration seed race. All 14 samples were connected,
the host and client processes stayed alive, and no sample contained an error,
but the result remains `partial` and is not acceptance evidence.

The race was fixed before the separate full 30-minute run was started. Do not
combine this directory with the completed run or use it to close the two-hour
host RSS no-growth gate.
