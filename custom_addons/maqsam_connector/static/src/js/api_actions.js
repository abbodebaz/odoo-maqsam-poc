/** @odoo-module **/

import { Component, onWillStart, useState } from "@odoo/owl";
import { registry } from "@web/core/registry";

async function api(url, options = {}) {
    const response = await fetch(url, {
        headers: { "Content-Type": "application/json", ...(options.headers || {}) },
        ...options,
    });
    const contentType = response.headers.get("content-type") || "";
    const body = contentType.includes("application/json")
        ? await response.json()
        : await response.text();
    if (!response.ok || (body && body.ok === false)) {
        throw new Error(body?.message || (typeof body === "string" ? body : `HTTP ${response.status}`));
    }
    return body;
}

function formatTime(timestamp) {
    if (!timestamp) return "—";
    const value = Number(timestamp);
    if (!Number.isFinite(value)) return "—";
    return new Date(value * 1000).toLocaleString("ar-SA");
}

function displayState(state) {
    if (state && typeof state === "object") {
        return state.name || state.state || JSON.stringify(state);
    }
    return state || "—";
}

export class MaqsamCallsAction extends Component {
    static template = "maqsam_connector.CallsAction";

    setup() {
        this.state = useState({
            loading: true,
            error: "",
            calls: [],
            page: 1,
            mine: true,
            selected: null,
            detailLoading: false,
            phone: "",
            caller: "",
            callMessage: "",
            callBusy: false,
        });
        onWillStart(() => this.loadCalls());
    }

    async loadCalls(page = this.state.page) {
        this.state.loading = true;
        this.state.error = "";
        try {
            const params = new URLSearchParams({ page: String(page) });
            if (this.state.mine) params.set("mine", "1");
            const result = await api(`/maqsam/api/calls?${params.toString()}`);
            this.state.calls = result.calls || [];
            this.state.page = result.page || page;
        } catch (error) {
            this.state.error = error.message;
        } finally {
            this.state.loading = false;
        }
    }

    async toggleMine() {
        this.state.mine = !this.state.mine;
        await this.loadCalls(1);
    }

    async nextPage() {
        if (this.state.calls.length < 100) return;
        await this.loadCalls(this.state.page + 1);
    }

    async previousPage() {
        if (this.state.page <= 1) return;
        await this.loadCalls(this.state.page - 1);
    }

    async openCall(call) {
        const referenceId = call.referenceId;
        const id = call.id;
        if (!referenceId && !id) return;
        this.state.detailLoading = true;
        this.state.selected = null;
        try {
            const lookup = referenceId ? "reference_id" : "id";
            const value = referenceId || id;
            const result = await api(`/maqsam/api/calls/${lookup}/${encodeURIComponent(value)}`);
            this.state.selected = result.call || {};
        } catch (error) {
            this.state.error = error.message;
        } finally {
            this.state.detailLoading = false;
        }
    }

    closeDetail() {
        this.state.selected = null;
    }

    async makeCall(event) {
        event.preventDefault();
        this.state.callMessage = "";
        this.state.callBusy = true;
        try {
            const result = await api("/maqsam/api/calls", {
                method: "POST",
                body: JSON.stringify({ phone: this.state.phone, caller: this.state.caller }),
            });
            const ref = result?.result?.call?.referenceId;
            this.state.callMessage = ref
                ? `تم بدء الاتصال — Reference: ${ref}`
                : "تم إرسال أمر الاتصال بنجاح";
            setTimeout(() => this.loadCalls(1), 1800);
        } catch (error) {
            this.state.callMessage = `خطأ: ${error.message}`;
        } finally {
            this.state.callBusy = false;
        }
    }

    callPhone(call) {
        if (call.type === "inbound") return call.callerNumber || call.caller || "—";
        return call.calleeNumber || call.callee || "—";
    }

    direction(call) {
        const labels = {
            inbound: "وارد",
            outbound: "صادر",
            internal: "داخلي",
            campaign: "حملة",
        };
        return labels[call.type] || call.type || "—";
    }

    agents(call) {
        return (call.agents || []).map((agent) => agent.name || agent.email).filter(Boolean).join("، ") || "—";
    }

    formatTime(timestamp) {
        return formatTime(timestamp);
    }

    summary(call) {
        const value = call?.summary;
        if (!value) return "";
        if (typeof value === "string") return value;
        if (typeof value === "object") return value.ar || value.en || Object.values(value)[0] || "";
        return String(value);
    }

    transcription(call) {
        const value = call?.transcription;
        if (!value) return "";
        return typeof value === "string" ? value : JSON.stringify(value, null, 2);
    }

    recordingUrl(call) {
        if (!call) return "";
        if (call.referenceId) {
            return `/maqsam/api/recordings/reference_id/${encodeURIComponent(call.referenceId)}?ts=${Date.now()}`;
        }
        if (call.id) {
            return `/maqsam/api/recordings/id/${encodeURIComponent(call.id)}?ts=${Date.now()}`;
        }
        return "";
    }
}

export class MaqsamAgentsAction extends Component {
    static template = "maqsam_connector.AgentsAction";

    setup() {
        this.state = useState({ loading: true, error: "", agents: [], page: 1 });
        onWillStart(() => this.loadAgents());
    }

    async loadAgents(page = this.state.page) {
        this.state.loading = true;
        this.state.error = "";
        try {
            const result = await api(`/maqsam/api/agents?page=${page}`);
            this.state.agents = result.agents || [];
            this.state.page = result.page || page;
        } catch (error) {
            this.state.error = error.message;
        } finally {
            this.state.loading = false;
        }
    }

    async nextPage() {
        if (this.state.agents.length < 100) return;
        await this.loadAgents(this.state.page + 1);
    }

    async previousPage() {
        if (this.state.page <= 1) return;
        await this.loadAgents(this.state.page - 1);
    }

    stateLabel(agent) {
        return displayState(agent.state);
    }

    createdAt(agent) {
        return formatTime(agent.createdAt);
    }
}

registry.category("actions").add("maqsam_connector.calls", MaqsamCallsAction);
registry.category("actions").add("maqsam_connector.agents", MaqsamAgentsAction);
