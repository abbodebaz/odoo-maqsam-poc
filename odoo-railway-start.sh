#!/usr/bin/env bash
set -euo pipefail

: "${PGHOST:?PGHOST is required}"
: "${PGPORT:=5432}"
: "${ADMIN_PGUSER:?ADMIN_PGUSER is required}"
: "${ADMIN_PGPASSWORD:?ADMIN_PGPASSWORD is required}"
: "${ADMIN_PGDATABASE:=railway}"
: "${ODOO_DB_USER:=odoo}"
: "${ODOO_DB_PASSWORD:?ODOO_DB_PASSWORD is required}"
: "${ODOO_DB_NAME:=odoo}"

ADDONS_PATH="/usr/lib/python3/dist-packages/odoo/addons,/mnt/extra-addons"

echo "Waiting for PostgreSQL at ${PGHOST}:${PGPORT}..."
export PGPASSWORD="${ADMIN_PGPASSWORD}"
until pg_isready -h "${PGHOST}" -p "${PGPORT}" -U "${ADMIN_PGUSER}" -d "${ADMIN_PGDATABASE}" >/dev/null 2>&1; do
  sleep 2
done

echo "Ensuring dedicated Odoo database role exists..."
ROLE_EXISTS="$(psql -h "${PGHOST}" -p "${PGPORT}" -U "${ADMIN_PGUSER}" -d "${ADMIN_PGDATABASE}" -tAc "SELECT 1 FROM pg_roles WHERE rolname='${ODOO_DB_USER}'" || true)"
if [ "${ROLE_EXISTS}" != "1" ]; then
  psql -v ON_ERROR_STOP=1 -h "${PGHOST}" -p "${PGPORT}" -U "${ADMIN_PGUSER}" -d "${ADMIN_PGDATABASE}" \
    -c "CREATE ROLE ${ODOO_DB_USER} WITH LOGIN CREATEDB PASSWORD '${ODOO_DB_PASSWORD}'"
else
  psql -v ON_ERROR_STOP=1 -h "${PGHOST}" -p "${PGPORT}" -U "${ADMIN_PGUSER}" -d "${ADMIN_PGDATABASE}" \
    -c "ALTER ROLE ${ODOO_DB_USER} WITH LOGIN CREATEDB PASSWORD '${ODOO_DB_PASSWORD}'"
fi

echo "Ensuring Odoo database exists..."
DB_EXISTS="$(psql -h "${PGHOST}" -p "${PGPORT}" -U "${ADMIN_PGUSER}" -d "${ADMIN_PGDATABASE}" -tAc "SELECT 1 FROM pg_database WHERE datname='${ODOO_DB_NAME}'" || true)"
if [ "${DB_EXISTS}" != "1" ]; then
  createdb -h "${PGHOST}" -p "${PGPORT}" -U "${ADMIN_PGUSER}" -O "${ODOO_DB_USER}" "${ODOO_DB_NAME}"
else
  psql -v ON_ERROR_STOP=1 -h "${PGHOST}" -p "${PGPORT}" -U "${ADMIN_PGUSER}" -d "${ADMIN_PGDATABASE}" \
    -c "ALTER DATABASE ${ODOO_DB_NAME} OWNER TO ${ODOO_DB_USER}"
fi

export PGPASSWORD="${ODOO_DB_PASSWORD}"

COMMON_ARGS=(
  "--db_host=${PGHOST}"
  "--db_port=${PGPORT}"
  "--db_user=${ODOO_DB_USER}"
  "--db_password=${ODOO_DB_PASSWORD}"
  "--addons-path=${ADDONS_PATH}"
  "--http-interface=0.0.0.0"
  "--http-port=8069"
  "--proxy-mode"
)

TABLE_EXISTS="$(psql -h "${PGHOST}" -p "${PGPORT}" -U "${ODOO_DB_USER}" -d "${ODOO_DB_NAME}" -tAc "SELECT to_regclass('public.ir_module_module')" || true)"
if [ "${TABLE_EXISTS}" != "ir_module_module" ]; then
  echo "Initializing Odoo database for the first time..."
  odoo "${COMMON_ARGS[@]}" -d "${ODOO_DB_NAME}" -i base --without-demo=all --stop-after-init
fi

MODULE_STATE="$(psql -h "${PGHOST}" -p "${PGPORT}" -U "${ODOO_DB_USER}" -d "${ODOO_DB_NAME}" -tAc "SELECT state FROM ir_module_module WHERE name='maqsam_connector' LIMIT 1" || true)"
if [ "${MODULE_STATE}" != "installed" ]; then
  echo "Installing Maqsam Connector module..."
  odoo "${COMMON_ARGS[@]}" -d "${ODOO_DB_NAME}" -i maqsam_connector --without-demo=all --stop-after-init
fi

echo "Starting Odoo 19..."
exec odoo "${COMMON_ARGS[@]}" -d "${ODOO_DB_NAME}" --db-filter="^${ODOO_DB_NAME}$"
