# Template Center Design Notes

## Why the Odoo record becomes immutable after submission
The provider owns the reviewed copy after it is submitted. Allowing Odoo users to edit the same local record would create a false representation of what Meta actually reviewed. A new editable copy is safer and auditable.

## Why advanced template creation is not guessed
WATI's public create endpoint documents advanced sub-categories and nested `header` / `buttons` containers, but the public page does not fully define every nested request object. The connector therefore imports and monitors advanced templates but does not manufacture undocumented payloads.

## Why template access is a workspace feature policy
Template creation/deletion is operationally sensitive. The same policy system used for Automation, Run Logs and Webhook Monitor controls the dashboard card, menu and model ACL so hiding the UI is never the only security boundary.

## Why raw provider snapshots are retained
Normalized fields drive the business UI; raw request/response snapshots are retained for system administrators only. This keeps the operator experience simple while preserving enough evidence to diagnose provider contract changes.
