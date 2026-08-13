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

plugin_paths=()
while IFS= read -r plugin_candidate; do
  plugin_paths+=("$plugin_candidate")
done < <(find "$temporary_dir/swift-protobuf/.build" -type f -name protoc-gen-swift -perm -u+x | sort)
case "$(uname -s)" in
  Darwin) protoc_platform="osx" ;;
  Linux) protoc_platform="linux" ;;
  *) echo "unsupported protoc host platform: $(uname -s)" >&2; exit 1 ;;
esac
case "$(uname -m)" in
  arm64|aarch64) protoc_arch="aarch_64" ;;
  x86_64) protoc_arch="x86_64" ;;
  *) echo "unsupported protoc host architecture: $(uname -m)" >&2; exit 1 ;;
esac
protoc_paths=()
while IFS= read -r protoc_candidate; do
  protoc_paths+=("$protoc_candidate")
done < <(find "$temporary_dir/swift-protobuf/.build/artifacts" -type f -path "*-${protoc_platform}-${protoc_arch}/bin/protoc" -perm -111 | sort)
if [[ ${#plugin_paths[@]} -ne 1 || ${#protoc_paths[@]} -ne 1 ]]; then
  echo "found ${#plugin_paths[@]} protoc-gen-swift candidates; expected exactly one" >&2
  echo "found ${#protoc_paths[@]} pinned protoc candidates; expected exactly one" >&2
  echo "unable to locate pinned protoc or protoc-gen-swift" >&2
  exit 1
fi
plugin_path="${plugin_paths[0]}"
protoc_path="${protoc_paths[0]}"

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
