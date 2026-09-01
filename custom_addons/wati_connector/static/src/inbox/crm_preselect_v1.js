(() => {
    "use strict";

    try {
        const params = new URLSearchParams(window.location.search || "");
        const conversationId = Number(params.get("conversation_id") || 0);
        if (conversationId > 0) {
            localStorage.setItem("watiInboxSelected", String(conversationId));
        }
    } catch (error) {
        console.warn("WATI CRM preselect skipped", error);
    }
})();
