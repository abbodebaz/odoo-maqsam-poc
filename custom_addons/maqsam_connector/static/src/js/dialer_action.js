/** @odoo-module **/

import { Component, onWillStart, useState } from "@odoo/owl";
import { registry } from "@web/core/registry";

export class MaqsamDialerAction extends Component {
    static template = "maqsam_connector.DialerAction";

    setup() {
        this.ensureTajawalFont();

        // Every mount requests a fresh local Odoo route so Maqsam's short-lived
        // autologin token is never reused from an old iframe/cache entry.
        this.dialerUrl = `/maqsam/dialer?ts=${Date.now()}`;
        this.state = useState({
            agentName: "موظف خدمة العملاء",
            agentEmail: "",
            agentState: "",
            agentLoaded: false,
            dialerReady: false,
        });

        onWillStart(async () => {
            await this.loadAgent();
        });
    }

    ensureTajawalFont() {
        const id = "maqsam-tajawal-font";
        if (document.getElementById(id)) {
            return;
        }
        const link = document.createElement("link");
        link.id = id;
        link.rel = "stylesheet";
        link.href = "https://fonts.googleapis.com/css2?family=Tajawal:wght@400;500;600;700;800&display=swap";
        document.head.appendChild(link);
    }

    async loadAgent() {
        try {
            const response = await fetch(`/maqsam/api/agents?ts=${Date.now()}`, {
                method: "GET",
                credentials: "same-origin",
                cache: "no-store",
                headers: { Accept: "application/json" },
            });
            if (!response.ok) {
                return;
            }
            const payload = await response.json();
            const agent = Array.isArray(payload.agents) ? payload.agents[0] : null;
            if (!agent) {
                return;
            }
            this.state.agentName = String(
                agent.name || agent.fullName || agent.displayName || agent.email || "موظف خدمة العملاء"
            );
            this.state.agentEmail = String(agent.email || agent.agentEmail || "");
            this.state.agentState = String(agent.state || agent.status || "");
            this.state.agentLoaded = true;
        } catch (_error) {
            // Agent metadata is decorative. Never block the working dialer.
        }
    }

    onDialerLoad() {
        this.state.dialerReady = true;
    }
}

registry.category("actions").add("maqsam_connector.dialer", MaqsamDialerAction);
