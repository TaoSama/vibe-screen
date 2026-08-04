#!/usr/bin/env bash
set -euo pipefail

readonly turn_port=13479
readonly turn_secret='peer-policy-turn-secret-0123456789-abcdefghijklmnopqrstuvwxyz'

for required_command in python3 turnserver turnutils_uclient; do
  if ! command -v "$required_command" >/dev/null 2>&1; then
    echo "missing required command: $required_command" >&2
    exit 1
  fi
done

work_dir=$(mktemp -d "${TMPDIR:-/tmp}/vibe-turn-peer-policy.XXXXXX")
turn_pid=''
cleanup() {
  local exit_status=$?
  if [[ -n "$turn_pid" ]]; then
    kill "$turn_pid" 2>/dev/null || true
    wait "$turn_pid" 2>/dev/null || true
  fi
  if ((exit_status == 0)); then
    rm -R -- "$work_dir"
  else
    echo "peer-policy artifacts retained at $work_dir" >&2
  fi
  trap - EXIT
  exit "$exit_status"
}
trap cleanup EXIT

policy_file=$work_dir/peer-policy.conf
{
  printf '%s\n' \
    'denied-peer-ip=0.0.0.0-0.255.255.255' \
    'denied-peer-ip=10.0.0.0-10.255.255.255' \
    'denied-peer-ip=100.64.0.0-100.127.255.255' \
    'denied-peer-ip=127.0.0.0-127.255.255.255' \
    'denied-peer-ip=169.254.0.0-169.254.255.255' \
    'denied-peer-ip=172.16.0.0-172.31.255.255' \
    'denied-peer-ip=192.0.0.0-192.0.0.255' \
    'denied-peer-ip=192.168.0.0-192.168.255.255' \
    'denied-peer-ip=198.18.0.0-198.19.255.255' \
    'denied-peer-ip=::ffff:0:0-::ffff:ffff:ffff' \
    'denied-peer-ip=fc00::-fdff:ffff:ffff:ffff:ffff:ffff:ffff:ffff' \
    'denied-peer-ip=fe80::-febf:ffff:ffff:ffff:ffff:ffff:ffff:ffff' \
    'denied-peer-ip=fec0::-feff:ffff:ffff:ffff:ffff:ffff:ffff:ffff'
} > "$policy_file"

while IFS= read -r policy_line; do
  if ! grep -Fxq "$policy_line" "$(dirname "$0")/../../../deploy/phase3/coturn/production.conf"; then
    echo "production coturn policy is missing: $policy_line" >&2
    exit 1
  fi
done < "$policy_file"

cat > "$work_dir/turnserver.conf" <<EOF
listening-ip=127.0.0.1
listening-ip=::1
relay-ip=127.0.0.1
relay-ip=::1
listening-port=$turn_port
realm=peer-policy.test
use-auth-secret
static-auth-secret=$turn_secret
fingerprint
min-port=49210
max-port=49350
no-multicast-peers
no-cli
no-tls
no-dtls
pidfile=$work_dir/turnserver.pid
log-file=stdout
simple-log
EOF
cat "$policy_file" >> "$work_dir/turnserver.conf"

turnserver -c "$work_dir/turnserver.conf" > "$work_dir/turnserver.log" 2>&1 &
turn_pid=$!
sleep 0.5
if ! kill -0 "$turn_pid" 2>/dev/null; then
  echo "coturn rejected the production peer policy" >&2
  exit 1
fi

read -r username password < <(python3 - "$turn_secret" <<'PY'
import base64, hashlib, hmac, sys, time
username = f"{int(time.time()) + 120}:peer-policy-device"
password = base64.b64encode(hmac.new(sys.argv[1].encode(), username.encode(), hashlib.sha1).digest()).decode()
print(username, password)
PY
)

for peer_address in 10.0.0.1 100.64.0.1 169.254.169.254 172.16.0.1 192.168.0.1 198.18.0.1; do
  log_file=$work_dir/$(tr '.:' '__' <<< "$peer_address").log
  turnutils_uclient -v -s -c -n 1 -u "$username" -w "$password" \
    -e "$peer_address" -r 9 -p "$turn_port" 127.0.0.1 > "$log_file" 2>&1 || true
  if ! grep -Eq '403|Forbidden IP' "$log_file"; then
    echo "CREATE_PERMISSION was not explicitly denied for $peer_address" >&2
    exit 1
  fi
done

ipv6_loopback_log=$work_dir/ipv6-loopback.log
turnutils_uclient -v -s -c -x -n 1 -u "$username" -w "$password" \
  -e ::1 -r 9 -p "$turn_port" ::1 > "$ipv6_loopback_log" 2>&1 || true
if ! grep -Eq '403|Forbidden IP' "$ipv6_loopback_log"; then
  echo "IPv6 loopback CREATE_PERMISSION was not explicitly denied" >&2
  exit 1
fi

public_log=$work_dir/public-control.log
turnutils_uclient -v -s -c -n 1 -u "$username" -w "$password" \
  -e 192.0.2.1 -r 9 -p "$turn_port" 127.0.0.1 > "$public_log" 2>&1 || true
if grep -Eq 'create permission error 403|Forbidden IP' "$public_log" \
  || ! grep -Eq 'create perm sent: 192\.0\.2\.1:9' "$public_log" \
  || ! grep -A2 'create perm sent: 192\.0\.2\.1:9' "$public_log" | grep -q 'success'; then
  echo "public IPv4 CREATE_PERMISSION control was not allowed" >&2
  exit 1
fi

echo "PASS: production peer ACL parsed and CREATE_PERMISSION returned explicit 403 for private, CGNAT, link-local, and internal ranges"
