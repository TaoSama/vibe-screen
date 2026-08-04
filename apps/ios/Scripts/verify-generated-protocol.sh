#!/usr/bin/env bash
set -euo pipefail

script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
repository_dir="$(cd "$script_dir/../../.." && pwd)"
bindings_path="apps/ios/Sources/VibeScreenProtocol"

"$script_dir/generate-protocol.sh"

generation_status="$(git -C "$repository_dir" status --porcelain=v1 --untracked-files=all -- "$bindings_path")"
if [[ -n "$generation_status" ]]; then
  echo "generated iOS Protocol v1 bindings are not current:" >&2
  echo "$generation_status" >&2
  exit 1
fi

echo "generated iOS Protocol v1 bindings are current"
