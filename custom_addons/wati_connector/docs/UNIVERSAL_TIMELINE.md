# Universal WhatsApp Timeline

The Smart WhatsApp Button can be enabled on any Odoo form. Each active Smart Button location also exposes a **WhatsApp Timeline** action for the same record.

The timeline resolves history using both:

1. The partner configured by `partner_path`, when available.
2. The WhatsApp phone number resolved by the Smart Button location.

This lets CRM leads and other records show historical WhatsApp messages even when they are not yet linked to a `res.partner` record.

The existing `res.partner` WhatsApp tab remains available as the full customer timeline.
