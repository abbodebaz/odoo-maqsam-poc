# Troubleshooting

## The addon is not visible in Apps

- Confirm the addon directories are inside an Odoo `addons_path`.
- Restart Odoo.
- Update the Apps list in Developer Mode.
- Check filesystem permissions.

## Module installation or upgrade fails

- Read the Odoo server log for the first traceback/error.
- Confirm the target server is Odoo 19.0.
- Confirm required Odoo dependencies are installed.
- Confirm all WATI addon directories in the delivery package come from the same release version.
- Restore the backup if the production upgrade cannot be completed safely.

## WATI connection test fails

- Verify the customer's WATI API endpoint and token.
- Confirm outbound HTTPS access from the Odoo server.
- Confirm the WATI account has the API capabilities required by the connector.

## Inbound messages do not appear

- Verify the webhook URL in WATI exactly matches the URL shown in Odoo.
- Confirm the Odoo instance is reachable from the internet over HTTPS.
- Review WATI webhook delivery and Odoo webhook-monitoring logs.

## Outbound messages fail

- Confirm the recipient phone number is valid and normalized.
- Check whether a session message is allowed or an approved template is required.
- Review the connector error/message logs rather than retrying blindly.

## Smart button is missing

- Confirm a Smart Button Location is active for the model/form.
- Confirm phone mapping is ready.
- Confirm the current user has WATI Agent or permitted administrator access.
- Reload the Odoo web client after configuration changes.

## Support data to collect

When escalating a problem, provide:

- Odoo version/build.
- WATI connector version.
- Installed WATI optional modules.
- Timestamp of the failed action.
- Odoo log excerpt around the error (without secrets).
- Relevant WATI response/error ID if available.
