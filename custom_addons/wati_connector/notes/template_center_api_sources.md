# Official WATI references used for Template Center

- Create template: `POST /api/v1/whatsApp/templates`
- List templates: `GET /api/v1/getMessageTemplates`
- Delete one template language: `DELETE /api/v1/whatsApp/templates/{wabaId}/{name}/{language}`
- Template status webhook: `templateReviewed`
- Template quality webhook: `templateQualityUpdated`
- Template category webhook: `templateCategoryUpdated`

These references are intentionally isolated from transport code so provider changes can be updated in one boundary without rewriting Odoo views or business models.
