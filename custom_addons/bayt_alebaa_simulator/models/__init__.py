from . import simulator_models
from . import simulator_control

from odoo import fields, models


class BaytAlebaaSimulatorAccountingFix(models.Model):
    _inherit = "bayt.alebaa.simulator"

    def _sim_account(self, code, name, account_type, reconcile=False):
        Account = self.env["account.account"].with_company(self.env.company)
        account = Account.search([("code", "=", code)], limit=1)
        if account:
            return account
        vals = {
            "name": name,
            "code": code,
            "account_type": account_type,
            "reconcile": reconcile,
        }
        if "company_ids" in Account._fields:
            vals["company_ids"] = [(6, 0, [self.env.company.id])]
        elif "company_id" in Account._fields:
            vals["company_id"] = self.env.company.id
        return Account.create(vals)

    def _prepare_simulator_accounting(self, partner):
        income = self._sim_account("SIM410000", "Simulator Sales Revenue", "income")
        receivable = self._sim_account("SIM110000", "Simulator Receivable", "asset_receivable", reconcile=True)
        outstanding = self._sim_account("SIM119000", "Simulator Outstanding Receipts", "asset_current", reconcile=True)
        bank_account = self._sim_account("SIM101000", "Simulator Bank", "asset_cash", reconcile=True)

        if "property_account_receivable_id" in partner._fields:
            partner.with_company(self.env.company).property_account_receivable_id = receivable

        company = self.env.company
        if "transfer_account_id" in company._fields:
            company.transfer_account_id = outstanding

        sale_journal = self._ensure_journal("sale")
        if "default_account_id" in sale_journal._fields and not sale_journal.default_account_id:
            sale_journal.default_account_id = income

        bank_journal = self._ensure_journal("bank")
        if "default_account_id" in bank_journal._fields:
            bank_journal.default_account_id = bank_account

        inbound_lines = bank_journal.inbound_payment_method_line_ids
        if inbound_lines and "payment_account_id" in inbound_lines._fields:
            inbound_lines.write({"payment_account_id": outstanding.id})

        return {
            "income": income,
            "receivable": receivable,
            "outstanding": outstanding,
            "bank": bank_account,
            "sale_journal": sale_journal,
            "bank_journal": bank_journal,
            "payment_method_line": inbound_lines[:1],
        }

    def _create_invoice(self, partner, product):
        setup = self._prepare_simulator_accounting(partner)
        vals = {
            "move_type": "out_invoice",
            "journal_id": setup["sale_journal"].id,
            "partner_id": partner.id,
            "invoice_line_ids": [(0, 0, {
                "product_id": product.id,
                "name": product.display_name,
                "quantity": 1,
                "price_unit": 451.03,
                "account_id": setup["income"].id,
            })],
        }
        rec = self.env["account.move"].create(vals)
        return rec, {
            "state": rec.state,
            "move_type": rec.move_type,
            "amount_total": rec.amount_total,
            "journal": setup["sale_journal"].display_name,
            "income_account": setup["income"].display_name,
            "receivable_account": setup["receivable"].display_name,
        }

    def _create_payment(self, partner, sale):
        setup = self._prepare_simulator_accounting(partner)
        vals = {
            "payment_type": "inbound",
            "partner_type": "customer",
            "partner_id": partner.id,
            "amount": 1300,
            "journal_id": setup["bank_journal"].id,
            "date": fields.Date.context_today(self),
        }
        if setup["payment_method_line"] and "payment_method_line_id" in self.env["account.payment"]._fields:
            vals["payment_method_line_id"] = setup["payment_method_line"].id
        if "sale_order_id" in self.env["account.payment"]._fields and sale:
            vals["sale_order_id"] = sale.id
        rec = self.env["account.payment"].create(vals)
        return rec, {
            "state": rec.state,
            "amount": rec.amount,
            "journal": setup["bank_journal"].display_name,
            "outstanding_account": setup["outstanding"].display_name,
        }
