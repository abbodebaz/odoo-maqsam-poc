# Odoo × Maqsam POC

Proof of concept for running **Odoo 19 Community** on Railway with an embedded **Maqsam Dialer**.

> Railway POC is configured to install `maqsam_connector` during deployment before starting Odoo.

## Architecture

- Odoo 19 Community
- PostgreSQL on Railway
- Custom Odoo addon: `maqsam_connector`
- Maqsam Autologin API
- Maqsam Dialer embedded inside Odoo

## Railway deployment

### 1. Deploy this repository

Create a Railway project and deploy this GitHub repository as a service. Railway should detect the root `Dockerfile` automatically.

The Odoo container listens on port:

```text
8069
```

When generating a public domain in Railway, set the target port to `8069` if Railway does not detect it automatically.

### 2. Add PostgreSQL

In the same Railway project add a PostgreSQL service.

In the Odoo service, create variable references to the PostgreSQL service for:

```text
PGHOST
PGPORT
PGUSER
PGPASSWORD
PGDATABASE
```

The official Odoo 19 Docker entrypoint understands the standard PostgreSQL variables `PGHOST`, `PGPORT`, `PGUSER`, and `PGPASSWORD`.

### 3. Persistent storage

Add a Railway Volume to the Odoo service and mount it at:

```text
/var/lib/odoo
```

This preserves the Odoo filestore between deployments.

### 4. Open Odoo

Generate a Railway public domain for the Odoo service and open it in the browser.

Create your Odoo database and log in as administrator.

### 5. Install the connector

In Odoo:

1. Open **Apps**.
2. Update the Apps List if needed.
3. Search for **Maqsam Connector**.
4. Install it.

The module is located at:

```text
custom_addons/maqsam_connector
```

## Configure Maqsam

After installing the addon, open Odoo Settings and find the **Maqsam** section.

Enter:

- Maqsam Base URL
- Access Key ID
- Access Secret
- Default Caller Number (optional)

The Access Secret is used server-side by Odoo and is not included in the browser URL.

### Map an Odoo user to a Maqsam agent

Open the Odoo user record and set:

```text
Maqsam Agent Email
```

If it is empty, the connector falls back to the Odoo user's email/login.

## Test the Dialer

Open the new **Maqsam → Dialer** menu inside Odoo.

Odoo calls its own server route:

```text
/maqsam/dialer
```

The server requests a short-lived Maqsam Autologin token and redirects the iframe to the Maqsam Dialer.

Expected user experience:

```text
Odoo
 └── Maqsam
      └── Dialer
           ├── Outgoing calls
           └── Incoming calls
```

The employee stays inside Odoo while the Maqsam Dialer handles voice and call controls.

## Next POC steps

After deployment is verified, the next additions are:

- Call button on CRM leads and Contacts
- Auto-fill the customer's phone number
- Incoming-call popup inside Odoo
- Lookup caller in `res.partner`
- Open the customer record automatically
- Call history inside the customer timeline
- Maqsam Notify webhook integration
- Agent availability/status inside Odoo

## Security

Do not commit real Maqsam API credentials to GitHub. Configure credentials through Odoo Settings or Railway secrets only.
