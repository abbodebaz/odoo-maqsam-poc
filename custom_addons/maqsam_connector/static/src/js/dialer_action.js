/** @odoo-module **/

import { Component } from "@odoo/owl";
import { registry } from "@web/core/registry";

export class MaqsamDialerAction extends Component {
    static template = "maqsam_connector.DialerAction";

    setup() {
        // Match the proven RTC POC exactly: every mount requests a fresh
        // local Odoo route so Maqsam's one-minute autologin token is never
        // reused from an old iframe/navigation cache entry.
        this.dialerUrl = `/maqsam/dialer?ts=${Date.now()}`;
    }
}

registry.category("actions").add("maqsam_connector.dialer", MaqsamDialerAction);
