#!/bin/sh
set -eu

script_dir=$(CDPATH='' cd -- "$(dirname -- "$0")" && pwd)
secret_dir=${VIBE_AUTHORITY_SECRETS_DIR:-$(dirname -- "$script_dir")/secrets/authority}
umask 077
mkdir -p "$secret_dir"
chmod 0700 "$secret_dir"

for secret_name in postgres_password admin_token signaling_token relay_token coturn_token role_token_secret; do
  destination=$secret_dir/$secret_name.txt
  if [ -e "$destination" ]; then
    echo "refusing to overwrite $destination" >&2
    exit 1
  fi
done
for secret_name in postgres_password admin_token signaling_token relay_token coturn_token role_token_secret; do
  destination=$secret_dir/$secret_name.txt
  openssl rand -hex 32 > "$destination"
done

postgres_password=$(tr -d '\r\n' < "$secret_dir/postgres_password.txt")
database_url="postgres://authority:$postgres_password@postgres:5432/vibe_authority?sslmode=disable"
printf '%s\n' "$database_url" > "$secret_dir/migration_database_url.txt"
printf '%s\n' "$database_url" > "$secret_dir/database_url.txt"
chmod 0600 "$secret_dir"/*.txt

echo "generated operator-readable local Authority secrets under $secret_dir"
