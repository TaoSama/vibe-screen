#!/bin/sh
set -eu

script_dir=$(CDPATH='' cd -- "$(dirname -- "$0")" && pwd)
secret_dir=$(dirname -- "$script_dir")/secrets
umask 077
mkdir -p "$secret_dir"

for secret_name in turn_secret client_token usage_token metrics_token admin_token authority_token; do
  destination=$secret_dir/$secret_name.txt
  if [ -e "$destination" ]; then
    echo "refusing to overwrite $destination" >&2
    exit 1
  fi
  openssl rand -base64 48 > "$destination"
done

echo "generated six mode-0600 secret files under $secret_dir"
