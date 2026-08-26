#!/usr/bin/env bash
set -euo pipefail

: "${PGHOST:?PGHOST is required}"
: "${PGPORT:=5432}"
: "${PGUSER:?PGUSER is required}"
: "${PGPASSWORD:?PGPASSWORD is required}"
: "${PGDATABASE:=odoo}"

ADDONS_PATH="/usr/lib/python3/dist-packages/odoo/addons,/mnt/extra-addons"
export PGPASSWORD

echo "Waiting for PostgreSQL at ${PGHOST}:${PGPORT}..."
until pg_isready -h "${PGHOST}" -p "${PGPORT}" -U "${PGUSER}" -d "${PGDATABASE}" >/dev/null 2>&1; do
  sleep 2
done

echo "PostgreSQL is ready."

COMMON_ARGS=(
  "--db_host=${PGHOST}"
  "--db_port=${PGPORT}"
  "--db_user=${PGUSER}"
  "--db_password=${PGPASSWORD}"
  "--addons-path=${ADDONS_PATH}"
  "--http-interface=0.0.0.0"
  "--http-port=8069"
  "--proxy-mode"
)

TABLE_EXISTS="$(psql -h "${PGHOST}" -p "${PGPORT}" -U "${PGUSER}" -d "${PGDATABASE}" -tAc "SELECT to_regclass('public.ir_module_module')" || true)"
if [ "${TABLE_EXISTS}" != "ir_module_module" ]; then
  echo "Initializing Odoo database for the first time..."
  odoo "${COMMON_ARGS[@]}" -d "${PGDATABASE}" -i base --without-demo=all --stop-after-init
fi

MODULE_STATE="$(psql -h "${PGHOST}" -p "${PGPORT}" -U "${PGUSER}" -d "${PGDATABASE}" -tAc "SELECT state FROM ir_module_module WHERE name='maqsam_connector' LIMIT 1" || true)"
if [ "${MODULE_STATE}" != "installed" ]; then
  echo "Installing Maqsam Connector module..."
  odoo "${COMMON_ARGS[@]}" -d "${PGDATABASE}" -i maqsam_connector --without-demo=all --stop-after-init
fi

echo "Starting Odoo 19..."
exec odoo "${COMMON_ARGS[@]}" -d "${PGDATABASE}" --db-filter="^${PGDATABASE}$"
