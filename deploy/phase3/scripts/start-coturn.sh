#!/bin/sh
set -eu

config_file=${COTURN_CONFIG_FILE:-/etc/vibe-coturn/local.conf}
secret_file=${VIBE_RELAY_TURN_SECRET_FILE:-/run/secrets/turn_secret}
runtime_config=${COTURN_RUNTIME_CONFIG:-/tmp/vibe-turnserver.conf}
production_config=false
case "$config_file" in
  */production.conf|production.conf) production_config=true ;;
esac

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

if [ "$production_config" = true ]; then
  if [ -z "${COTURN_EXTERNAL_IP:-}" ]; then
    echo "COTURN_EXTERNAL_IP is required for production coturn config" >&2
    exit 1
  fi
  if [ -z "${COTURN_REALM:-}" ]; then
    echo "COTURN_REALM is required for production coturn config" >&2
    exit 1
  fi
fi

if [ -n "${COTURN_EXTERNAL_IP:-}" ]; then
  external_ip=$(printf '%s' "$COTURN_EXTERNAL_IP" | tr '[:upper:]' '[:lower:]')
  case "$external_ip" in
    *[!0-9A-Fa-f:./]*)
      echo "COTURN_EXTERNAL_IP must be an IP or public/private IP mapping" >&2
      exit 1
      ;;
  esac
  public_ip=${external_ip%%/*}
  if [ -z "$public_ip" ]; then
    echo "COTURN_EXTERNAL_IP public side must be globally routable" >&2
    exit 1
  fi
  mapped_ipv4=
  case "$public_ip" in
    *:ffff:*)
      mapped_prefix=${public_ip%:ffff:*}
      if [ -z "$(printf '%s' "$mapped_prefix" | tr -d '0:')" ]; then
        mapped_ipv4=${public_ip##*:ffff:}
      fi
      ;;
  esac
  case "$mapped_ipv4" in
    *:*)
      echo "COTURN_EXTERNAL_IP IPv4-mapped public side must use dotted IPv4 notation" >&2
      exit 1
      ;;
  esac
  case "$public_ip" in
    0.*|10.*|127.*|169.254.*|172.1[6-9].*|172.2[0-9].*|172.3[0-1].*|192.0.2.*|192.168.*|198.18.*|198.19.*|198.51.100.*|203.0.113.*|224.*|225.*|226.*|227.*|228.*|229.*|23[0-9].*|24[0-9].*|25[0-5].*|100.6[4-9].*|100.[7-9][0-9].*|100.1[0-1][0-9].*|100.12[0-7].*|::|::1|0:0:0:0:0:0:0:0|fc*|fd*|fe8*|fe9*|fea*|feb*|fec*|fed*|fee*|fef*|ff*)
      echo "COTURN_EXTERNAL_IP public side must be globally routable" >&2
      exit 1
      ;;
  esac
  case "$mapped_ipv4" in
    0.*|10.*|127.*|169.254.*|172.1[6-9].*|172.2[0-9].*|172.3[0-1].*|192.0.2.*|192.168.*|198.18.*|198.19.*|198.51.100.*|203.0.113.*|100.6[4-9].*|100.[7-9][0-9].*|100.1[0-1][0-9].*|100.12[0-7].*)
      echo "COTURN_EXTERNAL_IP public side must be globally routable" >&2
      exit 1
      ;;
  esac
fi

if [ -n "${COTURN_REALM:-}" ]; then
  case "$COTURN_REALM" in
    *[!A-Za-z0-9.-]*)
      echo "COTURN_REALM must be a DNS hostname" >&2
      exit 1
      ;;
  esac
  coturn_realm=$(printf '%s' "${COTURN_REALM%.}" | tr '[:upper:]' '[:lower:]')
  if [ -z "$coturn_realm" ]; then
    echo "COTURN_REALM must be a production public DNS hostname" >&2
    exit 1
  fi
  case "$coturn_realm" in
    localhost|*.localhost|*.local|*.internal|*.corp|*.test|example|*.example|*.example.com|*.example.net|*.example.org|*.invalid)
      echo "COTURN_REALM must be a production public DNS hostname" >&2
      exit 1
      ;;
  esac
fi

umask 077
cp "$config_file" "$runtime_config"
printf '\nstatic-auth-secret=%s\n' "$turn_secret" >> "$runtime_config"
if [ -n "${COTURN_EXTERNAL_IP:-}" ]; then
  printf 'external-ip=%s\n' "$external_ip" >> "$runtime_config"
fi
if [ -n "${COTURN_REALM:-}" ]; then
  printf 'realm=%s\n' "$coturn_realm" >> "$runtime_config"
fi

exec turnserver -c "$runtime_config"
