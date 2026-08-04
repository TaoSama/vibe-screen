#!/usr/bin/env bash
set -euo pipefail

readonly turn_port=13478
readonly peer_port=13480
readonly relay_port=18090
readonly turn_secret='integration-turn-secret-0123456789-abcdefghijklmnopqrstuvwxyz'
readonly client_token='integration-client-token-0123456789-abcdefghijklmnopqrstuvwxyz'
readonly usage_token='integration-usage-token-0123456789-abcdefghijklmnopqrstuvwxyz'
readonly metrics_token='integration-metrics-token-0123456789-abcdefghijklmnopqrstuvwxyz'
readonly admin_token='integration-admin-token-0123456789-abcdefghijklmnopqrstuvwxyz'

keep_artifacts=false

usage() {
  echo "Usage: $0 [--keep-artifacts]"
}

while (($# > 0)); do
  case "$1" in
    --keep-artifacts)
      keep_artifacts=true
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      usage >&2
      exit 2
      ;;
  esac
  shift
done

for required_command in curl go python3 turnserver turnutils_peer turnutils_stunclient turnutils_uclient; do
  if ! command -v "$required_command" >/dev/null 2>&1; then
    echo "missing required command: $required_command" >&2
    exit 1
  fi
done

script_dir=$(CDPATH='' cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
relay_dir=$(CDPATH='' cd -- "$script_dir/.." && pwd)
work_dir=$(mktemp -d "${TMPDIR:-/tmp}/vibe-turn-integration.XXXXXX")
turn_pid=''
peer_pid=''
relay_pid=''
allocation_pids=()

cleanup() {
  local exit_status=$?
  local process_id
  for process_id in "$relay_pid" "$turn_pid" "$peer_pid" "${allocation_pids[@]}"; do
    if [[ -n "$process_id" ]]; then
      kill "$process_id" 2>/dev/null || true
    fi
  done
  wait 2>/dev/null || true
  if [[ "$keep_artifacts" == true ]]; then
    echo "integration artifacts retained at $work_dir"
  else
    rm -R -- "$work_dir" || true
  fi
  trap - EXIT
  exit "$exit_status"
}
trap cleanup EXIT

umask 077
printf '%s\n' "$turn_secret" > "$work_dir/turn-secret"
printf '%s\n' "$client_token" > "$work_dir/client-token"
printf '%s\n' "$usage_token" > "$work_dir/usage-token"
printf '%s\n' "$metrics_token" > "$work_dir/metrics-token"
printf '%s\n' "$admin_token" > "$work_dir/admin-token"

cat > "$work_dir/turnserver.conf" <<EOF
listening-ip=127.0.0.1
relay-ip=127.0.0.1
listening-port=$turn_port
realm=vibe-screen.integration
use-auth-secret
static-auth-secret=$turn_secret
fingerprint
stale-nonce=120
min-port=49160
max-port=49200
total-quota=20
user-quota=2
max-bps=20000000
no-multicast-peers
allow-loopback-peers
no-cli
no-tls
no-dtls
pidfile=$work_dir/turnserver.pid
log-file=stdout
simple-log
EOF

cat > "$work_dir/relay.json" <<EOF
{
  "listen_address": "127.0.0.1:$relay_port",
  "turn_realm": "vibe-screen.integration",
  "turn_uris": ["turn:127.0.0.1:$turn_port?transport=udp"],
  "credential_ttl_seconds": 120,
  "max_credential_ttl_seconds": 300,
  "credential_requests_per_minute": 12,
  "max_concurrent_sessions_per_device": 2,
  "daily_bytes_per_device": 1073741824,
  "max_usage_event_bytes": 67108864,
  "egress_microcents_per_gibibyte": 0,
  "state_file": "$work_dir/relay-state.json"
}
EOF

turnserver -c "$work_dir/turnserver.conf" > "$work_dir/turnserver.log" 2>&1 &
turn_pid=$!
turnutils_peer -L 127.0.0.1 -p "$peer_port" > "$work_dir/peer.log" 2>&1 &
peer_pid=$!

(
  cd "$relay_dir"
  go build -buildvcs=false -trimpath -o "$work_dir/vibe-relay" ./cmd/vibe-relay
)

VIBE_RELAY_TURN_SECRET_FILE="$work_dir/turn-secret" \
VIBE_RELAY_CLIENT_TOKEN_FILE="$work_dir/client-token" \
VIBE_RELAY_USAGE_TOKEN_FILE="$work_dir/usage-token" \
VIBE_RELAY_METRICS_TOKEN_FILE="$work_dir/metrics-token" \
VIBE_RELAY_ADMIN_TOKEN_FILE="$work_dir/admin-token" \
  "$work_dir/vibe-relay" --config "$work_dir/relay.json" > "$work_dir/relay.log" 2>&1 &
relay_pid=$!

ready=false
for _ in {1..100}; do
  if curl --fail --silent "http://127.0.0.1:$relay_port/readyz" >/dev/null \
    && turnutils_stunclient -p "$turn_port" 127.0.0.1 > "$work_dir/stun.log" 2>&1; then
    ready=true
    break
  fi
  sleep 0.1
done
if [[ "$ready" != true ]]; then
  echo "relay control plane or coturn did not become ready" >&2
  exit 1
fi

credential_response=$(curl --fail-with-body --silent --show-error \
  -H "Authorization: Bearer $client_token" \
  -H 'Content-Type: application/json' \
  -d '{"device_id":"integration-device","session_id":"integration-session","ttl_seconds":120}' \
  "http://127.0.0.1:$relay_port/v1/credentials")

username=$(python3 -c 'import json,sys; print(json.load(sys.stdin)["username"])' <<< "$credential_response")
password=$(python3 -c 'import json,sys; print(json.load(sys.stdin)["password"])' <<< "$credential_response")
realm=$(python3 -c 'import json,sys; print(json.load(sys.stdin)["realm"])' <<< "$credential_response")

if [[ "$username" != *:integration-device || "$username" == *:integration-session ]]; then
  echo "credential username did not use the stable device quota principal" >&2
  exit 1
fi
if [[ "$realm" != 'vibe-screen.integration' || ${#password} -lt 20 ]]; then
  echo "credential response is incomplete" >&2
  exit 1
fi

turnutils_uclient -v -G -c -n 5 \
  -u "$username" \
  -w "$password" \
  -e 127.0.0.1 \
  -r "$peer_port" \
  -p "$turn_port" \
  127.0.0.1 > "$work_dir/uclient.log" 2>&1

if ! grep -Eq 'tot_send_msgs=[1-9][0-9]*' "$work_dir/uclient.log" \
  || ! grep -Eq 'tot_recv_msgs=[1-9][0-9]*' "$work_dir/uclient.log" \
  || ! grep -Eq 'channel bind sent' "$work_dir/uclient.log" \
  || ! grep -Eq 'success(: 0x[0-9a-f]+)?$' "$work_dir/uclient.log"; then
  echo "TURN allocation did not exchange relayed packets" >&2
  exit 1
fi

echo "PASS: short-lived control-plane credential completed authenticated TURN allocation, permission/channel activity, and relayed packet exchange"
echo "coturn_version=$(turnserver --version 2>&1 | tail -n 1)"
echo "credential_username=$username"
grep -E 'tot_send_msgs=|tot_recv_msgs=' "$work_dir/uclient.log" | tail -n 2

issue_credential() {
  local session_id=$1
  local ttl_seconds=$2
  curl --fail-with-body --silent --show-error \
    -H "Authorization: Bearer $client_token" \
    -H 'Content-Type: application/json' \
    -d "{\"device_id\":\"quota-device\",\"session_id\":\"$session_id\",\"ttl_seconds\":$ttl_seconds}" \
    "http://127.0.0.1:$relay_port/v1/credentials"
}

first_quota_credential=$(issue_credential quota-session-1 120)
second_quota_credential=$(issue_credential quota-session-2 121)
third_quota_credential=$(issue_credential quota-session-3 122)

quota_username_1=$(python3 -c 'import json,sys; print(json.load(sys.stdin)["username"])' <<< "$first_quota_credential")
quota_password_1=$(python3 -c 'import json,sys; print(json.load(sys.stdin)["password"])' <<< "$first_quota_credential")
quota_username_2=$(python3 -c 'import json,sys; print(json.load(sys.stdin)["username"])' <<< "$second_quota_credential")
quota_password_2=$(python3 -c 'import json,sys; print(json.load(sys.stdin)["password"])' <<< "$second_quota_credential")
quota_username_3=$(python3 -c 'import json,sys; print(json.load(sys.stdin)["username"])' <<< "$third_quota_credential")
quota_password_3=$(python3 -c 'import json,sys; print(json.load(sys.stdin)["password"])' <<< "$third_quota_credential")
printf '%s\n' "$quota_password_1" > "$work_dir/quota-password-1"
printf '%s\n' "$quota_password_2" > "$work_dir/quota-password-2"
printf '%s\n' "$quota_password_3" > "$work_dir/quota-password-3"

if [[ "$quota_username_1" == "$quota_username_2" || "$quota_username_2" == "$quota_username_3" ]]; then
  echo "quota test did not issue different credential expiries" >&2
  exit 1
fi
for quota_username in "$quota_username_1" "$quota_username_2" "$quota_username_3"; do
  if [[ "$quota_username" != *:quota-device || "$quota_username" == *:quota-session-* ]]; then
    echo "session or expiry changed the device quota principal: $quota_username" >&2
    exit 1
  fi
done

for holder_number in 1 2; do
  username_variable=quota_username_$holder_number
  python3 "$script_dir/turn_allocation_helper.py" \
    --server-host 127.0.0.1 --server-port "$turn_port" \
    --username "${!username_variable}" --password-file "$work_dir/quota-password-$holder_number" \
    --expect-code 200 --hold-seconds 30 \
    --ready-file "$work_dir/quota-holder-$holder_number.ready" \
    --release-file "$work_dir/quota-holder-$holder_number.release" \
    > "$work_dir/quota-holder-$holder_number.log" 2>&1 &
  holder_pid=$!
  allocation_pids+=("$holder_pid")
done

holders_ready=false
holder_deadline=$((SECONDS + 15))
ready_code_is_200() {
  python3 -c 'import json,sys; raise SystemExit(0 if json.load(open(sys.argv[1], encoding="utf-8"))["code"] == 200 else 1)' "$1"
}
while ((SECONDS < holder_deadline)); do
  for holder_index in 0 1; do
    if [[ ! -s "$work_dir/quota-holder-$((holder_index + 1)).ready" ]] \
      && ! kill -0 "${allocation_pids[$holder_index]}" 2>/dev/null; then
      echo "quota holder $((holder_index + 1)) exited before allocation success" >&2
      tail -n 80 "$work_dir/quota-holder-$((holder_index + 1)).log" >&2
      exit 1
    fi
  done
  if [[ -s "$work_dir/quota-holder-1.ready" && -s "$work_dir/quota-holder-2.ready" ]] \
    && ready_code_is_200 "$work_dir/quota-holder-1.ready" \
    && ready_code_is_200 "$work_dir/quota-holder-2.ready" \
    && kill -0 "${allocation_pids[0]}" 2>/dev/null \
    && kill -0 "${allocation_pids[1]}" 2>/dev/null; then
    holders_ready=true
    break
  fi
  sleep 0.1
done
if [[ "$holders_ready" != true ]]; then
  echo "quota holders did not both reach allocation success before the 15-second deadline" >&2
  for holder_number in 1 2; do
    echo "--- quota-holder-$holder_number.log ---" >&2
    tail -n 80 "$work_dir/quota-holder-$holder_number.log" >&2
  done
  echo "--- turnserver.log ---" >&2
  tail -n 120 "$work_dir/turnserver.log" >&2
  exit 1
fi

python3 "$script_dir/turn_allocation_helper.py" \
  --server-host 127.0.0.1 --server-port "$turn_port" \
  --username "$quota_username_3" --password-file "$work_dir/quota-password-3" \
  --expect-code 486 > "$work_dir/quota-rejected.log" 2>&1

touch "$work_dir/quota-holder-1.release"
if ! wait "${allocation_pids[0]}"; then
  echo "quota holder failed to release its TURN allocation" >&2
  tail -n 80 "$work_dir/quota-holder-1.log" >&2
  exit 1
fi
if ! grep -q '"released": true' "$work_dir/quota-holder-1.log"; then
  echo "quota holder did not confirm Refresh lifetime=0" >&2
  tail -n 80 "$work_dir/quota-holder-1.log" >&2
  exit 1
fi
python3 "$script_dir/turn_allocation_helper.py" \
  --server-host 127.0.0.1 --server-port "$turn_port" \
  --username "$quota_username_3" --password-file "$work_dir/quota-password-3" \
  --expect-code 200 --transient-code 486 --wait-deadline-seconds 3 \
  > "$work_dir/quota-after-release.log" 2>&1

echo "PASS: exact single allocations share one coturn device principal; quota 486 and graceful Refresh lifetime=0 release are data-plane enforced"
