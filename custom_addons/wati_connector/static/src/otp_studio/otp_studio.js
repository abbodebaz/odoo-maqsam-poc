/** @odoo-module **/

import { Component, onWillStart, useState } from "@odoo/owl";
import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";

class WatiOtpStudio extends Component {
    static template = "wati_connector.WatiOtpStudio";

    setup() {
        this.orm = useService("orm");
        this.action = useService("action");
        this.notification = useService("notification");
        this.state = useState({
            loading: true,
            flows: [],
            filter: "all",
            query: "",
            kpis: { active: 0, waiting: 0, verifiedToday: 0, failed: 0 },
        });
        onWillStart(() => this.loadData());
    }

    async loadData() {
        this.state.loading = true;
        try {
            const flows = await this.orm.searchRead(
                "wati.otp.flow",
                [],
                [
                    "name",
                    "active",
                    "model_id",
                    "trigger_method",
                    "template_id",
                    "validity_minutes",
                    "mapping_state",
                    "mapping_summary",
                    "waiting_count",
                    "verified_count",
                    "failed_count",
                    "transaction_count",
                ],
                { order: "sequence, id", context: { active_test: false } }
            );
            this.state.flows = flows;
            const active = flows.filter((flow) => flow.active).length;
            const waiting = await this.orm.searchCount("wati.otp.transaction", [["state", "=", "sent"]]);
            const failed = await this.orm.searchCount("wati.otp.transaction", [["state", "in", ["failed", "expired", "locked"]]]);
            const today = new Date();
            today.setHours(0, 0, 0, 0);
            const verifiedToday = await this.orm.searchCount("wati.otp.transaction", [
                ["state", "=", "verified"],
                ["verified_at", ">=", today.toISOString().replace("T", " ").slice(0, 19)],
            ]);
            this.state.kpis = { active, waiting, verifiedToday, failed };
        } catch (error) {
            console.error("WATI OTP Studio load error", error);
            this.notification.add("OTP Bridge could not be loaded.", { type: "danger" });
        } finally {
            this.state.loading = false;
        }
    }

    get filteredFlows() {
        const query = (this.state.query || "").trim().toLowerCase();
        return this.state.flows.filter((flow) => {
            if (this.state.filter === "active" && !flow.active) return false;
            if (this.state.filter === "inactive" && flow.active) return false;
            if (this.state.filter === "attention" && flow.mapping_state === "ready") return false;
            if (!query) return true;
            const haystack = [
                flow.name,
                Array.isArray(flow.model_id) ? flow.model_id[1] : "",
                Array.isArray(flow.template_id) ? flow.template_id[1] : "",
            ].filter(Boolean).join(" ").toLowerCase();
            return haystack.includes(query);
        });
    }

    setFilter(filter) {
        this.state.filter = filter;
    }

    modelLabel(flow) {
        return Array.isArray(flow.model_id) ? flow.model_id[1] : "Record type not selected";
    }

    templateLabel(flow) {
        return Array.isArray(flow.template_id) ? flow.template_id[1] : "Not selected";
    }

    triggerLabel(flow) {
        if (flow.trigger_method === "field") return "Field trigger";
        if (flow.trigger_method === "hook") return "Integration hook";
        return "Manual action";
    }

    readinessLabel(flow) {
        return flow.mapping_state === "ready" ? "Ready" : "Needs setup";
    }

    async createFlow() {
        await this.action.doAction({
            type: "ir.actions.act_window",
            name: "Create OTP Flow",
            res_model: "wati.otp.flow",
            views: [[false, "form"]],
            target: "current",
            context: { default_setup_step: "source", default_active: false },
        });
    }

    async openFlow(flowId) {
        await this.action.doAction({
            type: "ir.actions.act_window",
            name: "OTP Flow",
            res_model: "wati.otp.flow",
            res_id: Number(flowId),
            views: [[false, "form"]],
            target: "current",
            context: { active_test: false },
        });
    }

    async openTransactions() {
        await this.action.doAction("wati_connector.action_wati_otp_transactions");
    }
}

registry.category("actions").add("wati_connector.otp_studio", WatiOtpStudio);
