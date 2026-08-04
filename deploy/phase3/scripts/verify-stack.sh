#!/usr/bin/env bash
set -euo pipefail

for required_command in curl docker python3; do
  if ! command -v "$required_command" >/dev/null 2>&1; then
    echo "missing required command: $required_command" >&2
    exit 1
  fi
done

script_dir=$(CDPATH='' cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
deploy_dir=$(CDPATH='' cd -- "$script_dir/.." && pwd)
client_token_file=$deploy_dir/secrets/client_token.txt

if [[ ! -r "$client_token_file" ]]; then
  echo "run scripts/generate-secrets.sh before verification" >&2
  exit 1
fi
client_token=$(tr -d '\r\n' < "$client_token_file")

ready=false
for _ in {1..50}; do
  if curl --fail --silent http://127.0.0.1:8090/readyz >/dev/null; then
    ready=true
    break
  fi
  sleep 0.2
done
if [[ "$ready" != true ]]; then
  echo "relay readiness check failed" >&2
  exit 1
fi

credential_response=$(curl --fail-with-body --silent --show-error \
  -H "Authorization: Bearer $client_token" \
  -H 'Content-Type: application/json' \
  -d '{"device_id":"compose-device","session_id":"compose-session","ttl_seconds":120}' \
  http://127.0.0.1:8090/v1/credentials)
username=$(python3 -c 'import json,sys; print(json.load(sys.stdin)["username"])' <<< "$credential_response")
password=$(python3 -c 'import json,sys; print(json.load(sys.stdin)["password"])' <<< "$credential_response")
client_log=$(mktemp "${TMPDIR:-/tmp}/vibe-compose-turn.XXXXXX")
trap 'rm -f -- "$client_log"' EXIT

(
  cd "$deploy_dir"
  docker compose exec -T coturn turnutils_uclient -v -y -c -n 3 \
    -u "$username" -w "$password" -p 3478 127.0.0.1
) > "$client_log" 2>&1

if ! grep -Eq 'tot_send_msgs=[1-9][0-9]*' "$client_log" \
  || ! grep -Eq 'tot_recv_msgs=[1-9][0-9]*' "$client_log"; then
  echo "containerized TURN packet exchange failed" >&2
  exit 1
fi

echo "PASS: Compose relay readiness, dynamic credential issuance, and coturn relayed packet exchange"
echo "credential_username=$username"
grep -E 'tot_send_msgs=|tot_recv_msgs=' "$client_log" | tail -n 2
