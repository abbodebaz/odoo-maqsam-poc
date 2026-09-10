# WhatsApp Template Center — Provider Contract

This document records the external contract intentionally supported by the Odoo WATI connector.

## Supported creation scope

Odoo creates **STANDARD** WhatsApp templates through WATI using:

- `POST /api/v1/whatsApp/templates`
- Categories: `UTILITY`, `MARKETING`
- Human creation method (`creationMethod = 0`)
- Text body with named or positional placeholders
- Optional footer
- No header/buttons for locally-created v1 templates until WATI documents those nested request objects sufficiently for a stable production contract

Authentication templates and advanced sub-categories (Carousel, Catalog, Checkout, Order Status, Limited Time Offer, etc.) can be synchronized and monitored when they already exist in WATI, but are not created from Odoo in this phase.

## Read / synchronization

The catalog is synchronized through the established WATI template list endpoint. Odoo normalizes provider-specific field names while preserving the raw provider snapshot for diagnostics.

## Deletion

One language variant is deleted through:

`DELETE /api/v1/whatsApp/templates/{wabaId}/{name}/{language}`

Odoo requires a known WABA ID before allowing provider deletion.

## Lifecycle webhooks

The connector handles:

- `templateReviewed`
- `templateQualityUpdated`
- `templateCategoryUpdated`

Provider callbacks update local approval status, quality, category and identifiers in the same database transaction as generic webhook ingestion.

## Safety rules

- A submitted/imported provider record is immutable in Odoo; users must create a new draft copy to change content.
- Remote templates cannot be deleted by deleting the Odoo row directly.
- HTTP 2xx alone is not considered success when the WATI payload explicitly reports `success=false`, `result=false` or a non-empty error structure.
- Provider access tokens are never persisted in template records or sent to the browser.
- Raw provider request/response snapshots are visible only to Odoo system administrators in the template form.
