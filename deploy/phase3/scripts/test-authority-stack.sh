#!/usr/bin/env bash
set -euo pipefail

for required_command in curl docker jq openssl; do
  if ! command -v "$required_command" >/dev/null 2>&1; then
    echo "missing required command: $required_command" >&2
    exit 1
  fi
done
docker compose version >/dev/null

script_dir=$(CDPATH='' cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
deploy_dir=$(CDPATH='' cd -- "$script_dir/.." && pwd)
compose_file=$deploy_dir/docker-compose.authority.yml
work_parent=${VIBE_AUTHORITY_STACK_WORK_ROOT:-$deploy_dir/../../.build}
mkdir -p "$work_parent"
work_parent=$(CDPATH='' cd -- "$work_parent" && pwd -P)
work_dir=$(mktemp -d "$work_parent/vibe-authority-stack.XXXXXX")
work_dir=$(CDPATH='' cd -- "$work_dir" && pwd -P)
export VIBE_AUTHORITY_SECRETS_DIR=$work_dir/secrets
export COMPOSE_PROJECT_NAME=vibe-authority-test-$$
export VIBE_AUTHORITY_PORT=${VIBE_AUTHORITY_PORT:-18091}

cleanup() {
  status=$?
  if [[ $status -ne 0 ]]; then
    compose ps >&2 || true
    diagnostic_log=$work_dir/failure.log
    compose logs --no-color authority-migrate authority postgres > "$diagnostic_log" 2>&1 || true
    safe_to_print=true
    while IFS= read -r secret_file; do
      secret=$(tr -d '\r\n' < "$secret_file")
      if grep -F -- "$secret" "$diagnostic_log" >/dev/null; then
        safe_to_print=false
        break
      fi
    done < <(find "$VIBE_AUTHORITY_SECRETS_DIR" -type f -name '*.txt' -print 2>/dev/null)
    if [[ $safe_to_print == true ]]; then
      cat "$diagnostic_log" >&2
    else
      echo "suppressed Authority container diagnostics containing a generated secret" >&2
    fi
  fi
  docker compose -f "$compose_file" down --volumes --remove-orphans >/dev/null 2>&1 || true
  rm -rf -- "$work_dir"
  return "$status"
}
trap cleanup EXIT

"$script_dir/generate-authority-secrets.sh"
admin_token=$(tr -d '\r\n' < "$VIBE_AUTHORITY_SECRETS_DIR/admin_token.txt")
signaling_token=$(tr -d '\r\n' < "$VIBE_AUTHORITY_SECRETS_DIR/signaling_token.txt")
base_url=http://127.0.0.1:$VIBE_AUTHORITY_PORT

compose() {
  docker compose -f "$compose_file" "$@"
}

wait_for_status() {
  local endpoint=$1 expected=$2
  for _ in {1..60}; do
    if [[ $(curl --silent --output /dev/null --write-out '%{http_code}' \
      --max-time 2 "$base_url$endpoint" || true) == "$expected" ]]; then
      return 0
    fi
    sleep 0.5
  done
  echo "timed out waiting for $endpoint status $expected" >&2
  compose ps >&2
  compose logs --no-color authority postgres >&2
  return 1
}

request() {
  local method=$1 endpoint=$2 token=$3 body=${4:-}
  local args=(--fail-with-body --silent --show-error --request "$method" \
    --header "Authorization: Bearer $token")
  if [[ -n "$body" ]]; then
    args+=(--header 'Content-Type: application/json' --data "$body")
  fi
  curl "${args[@]}" "$base_url$endpoint"
}

compose config --quiet
compose build authority-migrate authority

production_config=$work_dir/authority.production.json
cp "$deploy_dir/config/authority.production.example.json" "$production_config"
export VIBE_AUTHORITY_CONFIG_FILE=$production_config
export VIBE_AUTHORITY_IMAGE_REPOSITORY=vibe-screen-authority
export VIBE_AUTHORITY_IMAGE_SHA256=0000000000000000000000000000000000000000000000000000000000000000
export VIBE_AUTHORITY_MIGRATION_DATABASE_URL_FILE=$VIBE_AUTHORITY_SECRETS_DIR/migration_database_url.txt
export VIBE_AUTHORITY_DATABASE_URL_FILE=$VIBE_AUTHORITY_SECRETS_DIR/database_url.txt
export VIBE_AUTHORITY_ADMIN_TOKEN_FILE=$VIBE_AUTHORITY_SECRETS_DIR/admin_token.txt
export VIBE_AUTHORITY_SIGNALING_TOKEN_FILE=$VIBE_AUTHORITY_SECRETS_DIR/signaling_token.txt
export VIBE_AUTHORITY_RELAY_TOKEN_FILE=$VIBE_AUTHORITY_SECRETS_DIR/relay_token.txt
export VIBE_AUTHORITY_COTURN_TOKEN_FILE=$VIBE_AUTHORITY_SECRETS_DIR/coturn_token.txt
export VIBE_AUTHORITY_ROLE_TOKEN_SECRET_FILE=$VIBE_AUTHORITY_SECRETS_DIR/role_token_secret.txt
docker compose -f "$deploy_dir/docker-compose.authority.production.yml" config --quiet

compose up --detach --wait postgres authority
migration_container=$(compose ps --all --quiet authority-migrate)
test -n "$migration_container"
test "$(docker inspect --format '{{.State.ExitCode}}' "$migration_container")" = 0
wait_for_status /healthz 200
wait_for_status /readyz 200

request PUT /v1/accounts/compose-account "$admin_token"
request PUT /v1/accounts/compose-account/devices/compose-host "$admin_token"
request PUT /v1/accounts/compose-account/devices/compose-client "$admin_token"
session=$(request POST /v1/signaling/sessions "$signaling_token" \
  '{"request_id":"compose-request","account_id":"compose-account","host_device_id":"compose-host","client_device_id":"compose-client","session_epoch":1,"ttl_seconds":600}')
session_id=$(jq -er '.session_id' <<<"$session")
client_token=$(jq -er '.client_token' <<<"$session")
authorize_body=$(jq -nc --arg token "$client_token" '{role_token:$token}')
test "$(request POST "/v1/signaling/sessions/$session_id/authorize" "$signaling_token" "$authorize_body" | jq -r .role)" = client

compose restart authority
wait_for_status /readyz 200
test "$(request POST "/v1/signaling/sessions/$session_id/authorize" "$signaling_token" "$authorize_body" | jq -r .role)" = client

compose stop postgres
wait_for_status /healthz 200
wait_for_status /readyz 503
write_status=$(curl --silent --output /dev/null --write-out '%{http_code}' --max-time 10 \
  --request PUT --header "Authorization: Bearer $admin_token" \
  "$base_url/v1/accounts/fail-closed-account" || true)
test "$write_status" = 503

compose start postgres
compose up --detach --wait postgres
compose restart authority
wait_for_status /readyz 200
test "$(request POST "/v1/signaling/sessions/$session_id/authorize" "$signaling_token" "$authorize_body" | jq -r .role)" = client

inspect=$(docker inspect "$(compose ps --quiet authority)")
jq -e '.[0].Config.User == "65532:65532" and .[0].HostConfig.ReadonlyRootfs == true and (.[0].HostConfig.CapDrop | index("ALL")) != null' <<<"$inspect" >/dev/null

logs=$work_dir/stack.log
compose logs --no-color > "$logs"
while IFS= read -r secret_file; do
  secret=$(tr -d '\r\n' < "$secret_file")
  if grep -F -- "$secret" "$logs" >/dev/null; then
    echo "container logs leaked a generated secret" >&2
    exit 1
  fi
done < <(find "$VIBE_AUTHORITY_SECRETS_DIR" -type f -name '*.txt' -print)

echo "PASS: Authority image, migration order, readiness, fail-closed storage, and restart persistence"
