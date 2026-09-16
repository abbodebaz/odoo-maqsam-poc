# WATI Connector Architecture

## Scope

`wati_connector` is the provider-facing WhatsApp core. It owns WATI configuration, API transport, webhooks, conversations, messages, inbox behavior, templates, media, interactive messages, assignment, automation, audit data, and connector-level security.

Business application integrations are optional add-ons and must not leak back into the core:

- `wati_connector_crm`
- `wati_connector_sale`
- `wati_connector_account`
- `wati_connector_project`
- Enterprise-specific integrations may be shipped separately.

## Runtime flow

```text
WhatsApp / Meta
      |
      v
     WATI
      |
      | REST API + Webhooks
      v
+---------------------------+
|      wati_connector       |
|                           |
|  Controllers              |
|      |                    |
|      v                    |
|  Services / WatiClient    |
|      |                    |
|      v                    |
|  Models + PostgreSQL      |
+---------------------------+
      |
      +--> optional CRM integration
      +--> optional Sales integration
      +--> optional Accounting integration
      +--> optional Project integration
```

## Architectural rules

### 1. Single WATI HTTP boundary

All authenticated WATI API traffic must go through `services/client.py`. Controllers and business models must not import `requests` or construct WATI API URLs directly.

Inbound media downloading is isolated in `services/media.py` because it has different security requirements such as redirect handling, size limits, and SSRF protection.

### 2. Central configuration

`services/config.py` is the source of truth for API endpoint, API token, channel, and webhook configuration. Endpoint and token normalization must not be duplicated elsewhere.

### 3. Thin controllers

Controllers validate HTTP input, enforce the current user's permissions, and delegate transport/business behavior to services or models. Long-lived business state belongs in PostgreSQL, not process memory.

### 4. Database-backed correctness

Message correlation, webhook state, ownership, audit trails, and request idempotency must remain correct with multiple Odoo workers or containers. In-memory dictionaries or locks may be used only as performance optimizations, never as the source of correctness.

### 5. Optional business integrations

The core manifest must not depend on CRM, Sales, Accounting, Project, Helpdesk, or Field Service. Each optional module owns its model inheritance, views, and automation presets.

### 6. Security roles

The connector uses explicit Odoo groups for operational permissions. Administrative access grants configuration and transfer capabilities but does not bypass conversation ownership when sending; ownership must be transferred first so the audit trail remains authoritative.

### 7. Upgrade discipline

Historical data corrections belong in versioned `migrations/` scripts. Production data XML must not execute one-off repair functions during every module upgrade.

### 8. Testability

Pure helpers are tested independently, and WATI transport is centralized so outbound API behavior can be mocked without contacting WATI. End-to-end UAT remains a separate release gate.

## Quality gate

The repository workflow validates at minimum:

- Python source compilation
- XML parsing
- manifest file references
- optional-module boundary leaks
- direct `requests` usage outside the approved service layer

The gate is intentionally strict: a new feature should extend the architecture rather than create a parallel transport or configuration path.
