#!/usr/bin/env bash
set -euo pipefail

script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ios_dir="$(cd "$script_dir/.." && pwd)"
repository_dir="$(cd "$ios_dir/../.." && pwd)"
swift_protobuf_revision="c6fe6442e6a64250495669325044052e113e990c"
temporary_dir="$(mktemp -d)"
trap 'rm -rf "$temporary_dir"' EXIT

git clone --quiet https://github.com/apple/swift-protobuf.git "$temporary_dir/swift-protobuf"
git -C "$temporary_dir/swift-protobuf" checkout --quiet "$swift_protobuf_revision"
swift build \
  --package-path "$temporary_dir/swift-protobuf" \
  --configuration release \
  --product protoc-gen-swift

plugin_path="$(find "$temporary_dir/swift-protobuf/.build" -type f -name protoc-gen-swift -perm -111 | head -n 1)"
protoc_path="$(find "$temporary_dir/swift-protobuf/.build/artifacts" -type f -path '*osx-aarch_64/bin/protoc' -perm -111 | head -n 1)"
if [[ -z "$plugin_path" || -z "$protoc_path" ]]; then
  echo "unable to locate pinned protoc or protoc-gen-swift" >&2
  exit 1
fi

output_dir="$ios_dir/Sources/VibeScreenProtocol"
rm -rf "$output_dir/vibescreen"
mkdir -p "$output_dir"
proto_files=()
while IFS= read -r proto_file; do
  proto_files+=("$proto_file")
done < <(find "$repository_dir/contracts/proto" -name '*.proto' -type f | sort)
"$protoc_path" \
  -I "$repository_dir/contracts/proto" \
  "--plugin=protoc-gen-swift=$plugin_path" \
  --swift_opt=Visibility=Public \
  "--swift_out=$output_dir" \
  "${proto_files[@]}"

echo "generated ${#proto_files[@]} Protocol v1 Swift files from $swift_protobuf_revision"
