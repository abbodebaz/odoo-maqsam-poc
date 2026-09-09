/** @odoo-module **/

import { Component, onWillStart, useState } from "@odoo/owl";
import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";

class WatiWorkspace extends Component {
    static template = "wati_connector.WatiWorkspace";

    setup() {
        this.orm = useService("orm");
        this.action = useService("action");
        this.notification = useService("notification");
        this.state = useState({
            loading: true,
            data: {
                features: [],
                kpis: {},
                connection: {},
                onboarding: [],
                onboarding_done: 0,
                onboarding_total: 0,
                is_admin: false,
            },
        });
        onWillStart(() => this.loadData());
    }

    async loadData() {
        this.state.loading = true;
        try {
            this.state.data = await this.orm.call(
                "wati.workspace.gateway",
                "get_dashboard_data",
                [],
                {}
            );
        } catch (error) {
            console.error("WATI workspace load error", error);
            this.notification.add("تعذر تحميل مساحة WhatsApp. حاول تحديث الصفحة.", {
                type: "danger",
            });
        } finally {
            this.state.loading = false;
        }
    }

    get onboardingPercent() {
        const total = Number(this.state.data.onboarding_total || 0);
        const done = Number(this.state.data.onboarding_done || 0);
        return total ? Math.round((done / total) * 100) : 0;
    }

    async openAction(actionXmlid) {
        if (!actionXmlid) return;
        await this.action.doAction(actionXmlid);
    }

    async openFeature(feature) {
        await this.openAction(feature.action);
    }

    async openInbox() {
        await this.openAction("wati_connector.action_wati_inbox");
    }

    async openAutomation() {
        await this.openAction("wati_connector.action_wati_automation_studio");
    }

    async openHelp() {
        await this.openAction("wati_connector.action_wati_help_center");
    }
}

class WatiHelpCenter extends Component {
    static template = "wati_connector.WatiHelpCenter";

    setup() {
        this.orm = useService("orm");
        this.action = useService("action");
        this.notification = useService("notification");
        this.state = useState({
            loading: true,
            query: "",
            sections: [],
            selectedArticleId: null,
        });
        onWillStart(() => this.loadContent());
    }

    async loadContent() {
        this.state.loading = true;
        try {
            const data = await this.orm.call(
                "wati.workspace.gateway",
                "get_help_content",
                [],
                {}
            );
            this.state.sections = data.sections || [];
            const firstSection = this.state.sections[0];
            const firstArticle = firstSection && firstSection.articles && firstSection.articles[0];
            this.state.selectedArticleId = firstArticle ? firstArticle.id : null;
        } catch (error) {
            console.error("WATI help center load error", error);
            this.notification.add("تعذر تحميل مركز المساعدة.", { type: "danger" });
        } finally {
            this.state.loading = false;
        }
    }

    get allArticles() {
        const rows = [];
        for (const section of this.state.sections) {
            for (const article of section.articles || []) {
                rows.push({ section, article });
            }
        }
        return rows;
    }

    get visibleArticles() {
        const query = (this.state.query || "").trim().toLowerCase();
        if (!query) return this.allArticles;
        return this.allArticles.filter(({ section, article }) => {
            const text = [
                section.title,
                article.title,
                article.summary,
                ...(article.steps || []),
                ...(article.tips || []),
            ]
                .filter(Boolean)
                .join(" ")
                .toLowerCase();
            return text.includes(query);
        });
    }

    get selectedArticle() {
        const current = this.allArticles.find(
            ({ article }) => article.id === this.state.selectedArticleId
        );
        if (current) return current;
        return this.visibleArticles[0] || this.allArticles[0] || null;
    }

    selectArticle(articleId) {
        this.state.selectedArticleId = articleId;
    }

    async backHome() {
        await this.action.doAction("wati_connector.action_wati_workspace");
    }

    async openSettings() {
        await this.action.doAction("wati_connector.action_wati_settings");
    }
}

registry.category("actions").add("wati_connector.workspace", WatiWorkspace);
registry.category("actions").add("wati_connector.help_center", WatiHelpCenter);
