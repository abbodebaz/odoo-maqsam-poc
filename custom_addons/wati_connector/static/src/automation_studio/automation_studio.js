/** @odoo-module **/

import { Component, onWillStart, useState } from "@odoo/owl";
import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";

class WatiAutomationStudio extends Component {
    static template = "wati_connector.WatiAutomationStudio";

    setup() {
        this.orm = useService("orm");
        this.action = useService("action");
        this.notification = useService("notification");
        this.state = useState({
            loading: true,
            rules: [],
            filter: "all",
            query: "",
            kpis: {
                active: 0,
                attention: 0,
                runsToday: 0,
                successRate: 100,
            },
        });
        onWillStart(() => this.loadData());
    }

    async loadData() {
        this.state.loading = true;
        try {
            const fields = [
                "name",
                "active",
                "human_summary",
                "template_name",
                "readiness_state",
                "run_count",
                "success_count",
                "failure_count",
                "setup_step",
                "model_id",
            ];
            const rules = await this.orm.searchRead(
                "wati.automation.rule",
                [],
                fields,
                { order: "sequence, id" }
            );
            this.state.rules = rules;

            const active = rules.filter((rule) => rule.active).length;
            const attention = rules.filter(
                (rule) => rule.readiness_state !== "ready"
            ).length;
            const success = rules.reduce(
                (sum, rule) => sum + Number(rule.success_count || 0),
                0
            );
            const failure = rules.reduce(
                (sum, rule) => sum + Number(rule.failure_count || 0),
                0
            );
            const finished = success + failure;
            const successRate = finished
                ? Math.round((success / finished) * 1000) / 10
                : 100;

            const today = new Date();
            today.setHours(0, 0, 0, 0);
            const runsToday = await this.orm.searchCount("wati.automation.log", [
                ["create_date", ">=", today.toISOString().replace("T", " ").slice(0, 19)],
            ]);

            this.state.kpis = { active, attention, runsToday, successRate };
        } catch (error) {
            console.error("WATI Automation Studio load error", error);
            this.notification.add("تعذر تحميل مركز الأتمتة.", { type: "danger" });
        } finally {
            this.state.loading = false;
        }
    }

    get filteredRules() {
        const query = (this.state.query || "").trim().toLowerCase();
        return this.state.rules.filter((rule) => {
            if (this.state.filter === "active" && !rule.active) return false;
            if (this.state.filter === "paused" && rule.active) return false;
            if (
                this.state.filter === "attention" &&
                rule.readiness_state === "ready"
            ) {
                return false;
            }
            if (!query) return true;
            const haystack = [
                rule.name,
                rule.human_summary,
                rule.template_name,
                Array.isArray(rule.model_id) ? rule.model_id[1] : "",
            ]
                .filter(Boolean)
                .join(" ")
                .toLowerCase();
            return haystack.includes(query);
        });
    }

    setFilter(filter) {
        this.state.filter = filter;
    }

    readinessLabel(state) {
        if (state === "ready") return "جاهزة";
        if (state === "warning") return "تحتاج مراجعة";
        return "غير مكتملة";
    }

    readinessClass(state) {
        if (state === "ready") return "is-ready";
        if (state === "warning") return "is-warning";
        return "is-incomplete";
    }

    modelLabel(rule) {
        return Array.isArray(rule.model_id) ? rule.model_id[1] : "Odoo";
    }

    async createAutomation() {
        await this.action.doAction({
            type: "ir.actions.act_window",
            name: "إنشاء أتمتة",
            res_model: "wati.automation.rule",
            views: [[false, "form"]],
            target: "current",
            context: { default_setup_step: "trigger", default_active: false },
        });
    }

    async openRule(ruleId) {
        await this.action.doAction({
            type: "ir.actions.act_window",
            name: "الأتمتة",
            res_model: "wati.automation.rule",
            res_id: Number(ruleId),
            views: [[false, "form"]],
            target: "current",
        });
    }

    async openLogs() {
        await this.action.doAction("wati_connector.action_wati_automation_logs");
    }
}

registry.category("actions").add(
    "wati_connector.automation_studio",
    WatiAutomationStudio
);
