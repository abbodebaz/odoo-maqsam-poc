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
  local label="$2"
  local module_state
  module_state="$(psql -h "${PGHOST}" -p "${PGPORT}" -U "${PGUSER}" -d "${PGDATABASE}" -tAc "SELECT state FROM ir_module_module WHERE name='${module_name}' LIMIT 1" || true)"
  if [ "${module_state}" = "installed" ]; then
    echo "Upgrading ${label} module..."
    odoo "${COMMON_ARGS[@]}" -d "${PGDATABASE}" -u "${module_name}" --without-demo --stop-after-init
  else
    echo "Installing ${label} module..."
    odoo "${COMMON_ARGS[@]}" -d "${PGDATABASE}" -i "${module_name}" --without-demo --stop-after-init
  fi
}

install_or_upgrade_module "maqsam_connector" "Maqsam Connector"
install_or_upgrade_module "wati_connector" "WATI WhatsApp Connector"

mkdir -p "${FILESTORE_DIR}"

# Railway containers use an ephemeral Odoo filestore. The database can retain
# generated bundle attachments whose files disappeared on a previous deploy.
# These are safe to delete on every deploy: Odoo recreates them on first load.
echo "Clearing generated Odoo web asset attachments..."
psql -v ON_ERROR_STOP=1 -h "${PGHOST}" -p "${PGPORT}" -U "${PGUSER}" -d "${PGDATABASE}" \
  -c "DELETE FROM ir_attachment WHERE COALESCE(url, '') LIKE '/web/assets/%' OR COALESCE(name, '') LIKE '/web/assets/%';"

# A short-lived WATI Inbox experiment temporarily assigned a client action to
# the root WhatsApp menu. After rolling back, Odoo can keep that numeric menu
# reference even though the client action record no longer exists, causing
# /web/webclient/load_menus to return 404. Explicitly restore the root menu to
# a container-only menu. Child actions (conversations/messages) remain intact.
echo "Clearing stale WATI root menu action..."
psql -v ON_ERROR_STOP=1 -h "${PGHOST}" -p "${PGPORT}" -U "${PGUSER}" -d "${PGDATABASE}" \
  -c "UPDATE ir_ui_menu SET action = NULL WHERE id IN (SELECT res_id FROM ir_model_data WHERE module = 'wati_connector' AND name = 'menu_wati_root' AND model = 'ir.ui.menu');"

echo "Starting Odoo 19..."
exec odoo "${COMMON_ARGS[@]}" -d "${PGDATABASE}" --db-filter="^${PGDATABASE}$"
