#!/bin/sh
set -eu

config_file=${COTURN_CONFIG_FILE:-/etc/vibe-coturn/local.conf}
secret_file=${VIBE_RELAY_TURN_SECRET_FILE:-/run/secrets/turn_secret}
runtime_config=/tmp/vibe-turnserver.conf

if [ ! -r "$config_file" ]; then
  echo "coturn configuration is not readable: $config_file" >&2
  exit 1
fi
if [ ! -r "$secret_file" ]; then
  echo "TURN REST secret is not readable: $secret_file" >&2
  exit 1
fi

turn_secret=$(tr -d '\r\n' < "$secret_file")
if [ "${#turn_secret}" -lt 32 ]; then
  echo "TURN REST secret must contain at least 32 characters" >&2
  exit 1
fi

umask 077
cp "$config_file" "$runtime_config"
printf '\nstatic-auth-secret=%s\n' "$turn_secret" >> "$runtime_config"

if [ -n "${COTURN_EXTERNAL_IP:-}" ]; then
  case "$COTURN_EXTERNAL_IP" in
    *[!0-9A-Fa-f:./]*)
      echo "COTURN_EXTERNAL_IP must be an IP or public/private IP mapping" >&2
      exit 1
      ;;
  esac
  printf 'external-ip=%s\n' "$COTURN_EXTERNAL_IP" >> "$runtime_config"
fi

if [ -n "${COTURN_REALM:-}" ]; then
  case "$COTURN_REALM" in
    *[!A-Za-z0-9.-]*)
      echo "COTURN_REALM must be a DNS hostname" >&2
      exit 1
      ;;
  esac
  printf 'realm=%s\n' "$COTURN_REALM" >> "$runtime_config"
fi

exec turnserver -c "$runtime_config"
