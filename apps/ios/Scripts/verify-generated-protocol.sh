#!/usr/bin/env bash
set -euo pipefail

script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
repository_dir="$(cd "$script_dir/../../.." && pwd)"
bindings_path="apps/ios/Sources/VibeScreenProtocol"
mac_bindings_path="baseline/MacHost/Protocol/Sources/VibeScreenProtocol"

"$script_dir/generate-protocol.sh"

generation_diff="$(git -C "$repository_dir" diff -- "$bindings_path")"
untracked_bindings="$(git -C "$repository_dir" ls-files --others --exclude-standard -- "$bindings_path")"
if [[ -n "$generation_diff" || -n "$untracked_bindings" ]]; then
  echo "generated iOS Protocol v1 bindings are not current:" >&2
  git -C "$repository_dir" status --short -- "$bindings_path" >&2
  exit 1
fi

if ! diff -qr "$repository_dir/$bindings_path" "$repository_dir/$mac_bindings_path"; then
  echo "generated macOS and iOS Protocol v1 bindings differ" >&2
  exit 1
fi

echo "generated macOS and iOS Protocol v1 bindings are current"
