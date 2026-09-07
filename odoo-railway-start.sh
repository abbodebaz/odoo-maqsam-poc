#!/usr/bin/env bash
set -euo pipefail

: "${PGHOST:?PGHOST is required}"
: "${PGPORT:=5432}"
: "${PGUSER:?PGUSER is required}"
: "${PGPASSWORD:?PGPASSWORD is required}"
: "${PGDATABASE:=odoo}"

ADDONS_PATH="/usr/lib/python3/dist-packages/odoo/addons,/mnt/extra-addons"
DATA_DIR="/var/lib/odoo"
FILESTORE_DIR="${DATA_DIR}/filestore/${PGDATABASE}"
WATI_MODULES="${WATI_MODULES:-wati_connector}"
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
  "--data-dir=${DATA_DIR}"
  "--http-interface=0.0.0.0"
  "--http-port=8069"
  "--proxy-mode"
)

TABLE_EXISTS="$(psql -h "${PGHOST}" -p "${PGPORT}" -U "${PGUSER}" -d "${PGDATABASE}" -tAc "SELECT to_regclass('public.ir_module_module')" || true)"
if [ "${TABLE_EXISTS}" != "ir_module_module" ]; then
  echo "Initializing Odoo database for the first time..."
  odoo "${COMMON_ARGS[@]}" -d "${PGDATABASE}" -i base --without-demo --stop-after-init
fi

install_or_upgrade_module() {
  local module_name="$1"
  local module_state
  module_state="$(psql -h "${PGHOST}" -p "${PGPORT}" -U "${PGUSER}" -d "${PGDATABASE}" -tAc "SELECT state FROM ir_module_module WHERE name='${module_name}' LIMIT 1" || true)"
  if [ "${module_state}" = "installed" ]; then
    echo "Upgrading ${module_name}..."
    odoo "${COMMON_ARGS[@]}" -d "${PGDATABASE}" -u "${module_name}" --without-demo --stop-after-init
  else
    echo "Installing ${module_name}..."
    odoo "${COMMON_ARGS[@]}" -d "${PGDATABASE}" -i "${module_name}" --without-demo --stop-after-init
  fi
}

IFS=',' read -ra MODULE_LIST <<< "${WATI_MODULES}"
for module_name in "${MODULE_LIST[@]}"; do
  module_name="$(echo "${module_name}" | xargs)"
  [ -n "${module_name}" ] || continue
  install_or_upgrade_module "${module_name}"
done

mkdir -p "${FILESTORE_DIR}"

# Generated web assets are reproducible and may point to files from an older
# ephemeral container. Removing only generated asset attachments is safe;
# Odoo recreates them on demand.
echo "Clearing generated Odoo web asset attachments..."
psql -v ON_ERROR_STOP=1 -h "${PGHOST}" -p "${PGPORT}" -U "${PGUSER}" -d "${PGDATABASE}" \
  -c "DELETE FROM ir_attachment WHERE COALESCE(url, '') LIKE '/web/assets/%' OR COALESCE(name, '') LIKE '/web/assets/%';"

echo "Starting Odoo 19..."
exec odoo "${COMMON_ARGS[@]}" -d "${PGDATABASE}" --db-filter="^${PGDATABASE}$"
