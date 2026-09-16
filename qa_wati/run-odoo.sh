#!/bin/sh
# QA-only Odoo startup. No WATI credentials or webhook changes.
set -eu
: "${ODOO_DATABASE_HOST:?Missing ODOO_DATABASE_HOST}"
: "${ODOO_DATABASE_USER:?Missing ODOO_DATABASE_USER}"
: "${ODOO_DATABASE_PASSWORD:?Missing ODOO_DATABASE_PASSWORD}"
: "${ODOO_DATABASE_NAME:?Missing ODOO_DATABASE_NAME}"
db_port="${ODOO_DATABASE_PORT:-5432}"
http_port="${PORT:-8069}"
case "$db_port" in *[!0-9]*|'') echo 'Invalid DB port' >&2; exit 2;; esac
case "$http_port" in *[!0-9]*|'') echo 'Invalid HTTP port' >&2; exit 2;; esac
exec /usr/bin/odoo \
  --http-interface=0.0.0.0 \
  --http-port="$http_port" \
  --db_host="$ODOO_DATABASE_HOST" \
  --db_port="$db_port" \
  --db_user="$ODOO_DATABASE_USER" \
  --db_password="$ODOO_DATABASE_PASSWORD" \
  --database="$ODOO_DATABASE_NAME" \
  --addons-path=/mnt/extra-addons,/usr/lib/python3/dist-packages/odoo/addons,/usr/lib/python3/dist-packages/addons \
  --proxy-mode \
  --without-demo=True
