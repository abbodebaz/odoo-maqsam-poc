#!/usr/bin/env python3
"""QA ONLY: create a separate database, install WATI core from the verified ZIP and verify state.

Never touches the existing railway DB, production resources, WATI API credentials, or optional integration addons.
"""
import os
import subprocess
import sys

import psycopg2
from psycopg2 import sql


def required(key):
    value = os.environ.get(key, '').strip()
    if not value:
        raise SystemExit(f'Missing {key}')
    return value


host = required('ODOO_DATABASE_HOST')
port = int(os.environ.get('ODOO_DATABASE_PORT') or '5432')
user = required('ODOO_DATABASE_USER')
password = required('ODOO_DATABASE_PASSWORD')
dbname = required('ODOO_DATABASE_NAME')
if dbname != 'wati_zip_qa':
    raise SystemExit('REFUSING INSTALL: QA database must be exactly wati_zip_qa')

connection_args = dict(host=host, port=port, user=user, password=password, connect_timeout=15)
print(f'QA_INSTALL_TARGET={dbname} (separate from railway)', flush=True)
with psycopg2.connect(dbname='postgres', **connection_args) as connection:
    connection.autocommit = True
    with connection.cursor() as cursor:
        cursor.execute('SELECT 1 FROM pg_database WHERE datname = %s', (dbname,))
        if cursor.fetchone():
            print('QA_DATABASE_ALREADY_EXISTS', flush=True)
        else:
            cursor.execute(sql.SQL('CREATE DATABASE {}').format(sql.Identifier(dbname)))
            print('QA_DATABASE_CREATED', flush=True)

args = [
    '/usr/bin/odoo',
    '--database=' + dbname,
    '--db_host=' + host,
    '--db_port=' + str(port),
    '--db_user=' + user,
    '--db_password=' + password,
    '--addons-path=/mnt/extra-addons,/usr/lib/python3/dist-packages/odoo/addons,/usr/lib/python3/dist-packages/addons',
    '--init=base,wati_connector',
    '--without-demo=all',
    '--max-cron-threads=0',
    '--stop-after-init',
]
print('QA_INSTALL_START module=w ati_connector'.replace('w ati', 'wati'), flush=True)
subprocess.run(args, check=True)
with psycopg2.connect(dbname=dbname, **connection_args) as connection:
    with connection.cursor() as cursor:
        cursor.execute('SELECT name, state FROM ir_module_module WHERE name = %s', ('wati_connector',))
        record = cursor.fetchone()
        if record != ('wati_connector', 'installed'):
            raise SystemExit(f'QA_CORE_INSTALL_NOT_CONFIRMED: {record!r}')
        cursor.execute('SELECT name, state FROM ir_module_module WHERE name IN (%s,%s,%s,%s) ORDER BY name', (
            'wati_connector_crm', 'wati_connector_sale', 'wati_connector_account', 'wati_connector_project'))
        optional = cursor.fetchall()
        incorrectly_installed = [name for name, state in optional if state == 'installed']
        if incorrectly_installed:
            raise SystemExit(f'QA_OPTIONAL_ADDON_UNEXPECTEDLY_INSTALLED: {incorrectly_installed}')
        print('QA_CORE_INSTALL_VERIFIED name=w ati_connector state=installed'.replace('w ati', 'wati'), flush=True)
        print('QA_OPTIONAL_MODULES_NOT_INSTALLED', flush=True)
