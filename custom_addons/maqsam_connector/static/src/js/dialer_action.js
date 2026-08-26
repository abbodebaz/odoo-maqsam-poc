/** @odoo-module **/

import { Component } from "@odoo/owl";
import { registry } from "@web/core/registry";

export class MaqsamDialerAction extends Component {
    static template = "maqsam_connector.DialerAction";
}

registry.category("actions").add("maqsam_connector.dialer", MaqsamDialerAction);
