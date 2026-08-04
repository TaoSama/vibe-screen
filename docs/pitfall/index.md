# Pitfalls

- Do not infer glass-to-glass latency from unsynchronized Mac and device
  clocks. Use an external high-frame-rate camera and retain the raw samples.
- Do not let media backlog grow to preserve old frames. Bound the queue and
  request a keyframe when inter-frame dependencies are no longer usable.
- Do not treat private `CGVirtualDisplay` availability as guaranteed. Keep a
  physical-display capture path and document a dummy-display fallback.
- Do not reuse or renumber Protobuf fields. Reserve removed field numbers and
  names permanently.
