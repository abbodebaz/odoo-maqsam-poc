(() => {
    "use strict";

    const chatNumber = document.getElementById("chatNumber");
    const partnerStatus = document.getElementById("drawerPartnerStatus");
    const partnerLink = document.getElementById("drawerPartnerLink");
    if (!chatNumber || !partnerStatus || !partnerLink) return;

    let lastConversationId = 0;
    let lastFetchAt = 0;

    function renderUnlinked() {
        partnerStatus.textContent = "غير مربوط بعميل Odoo";
        partnerLink.removeAttribute("href");
        partnerLink.classList.add("is-hidden");
    }

    async function refreshPartnerInfo(force = false) {
        const conversationId = Number(localStorage.getItem("watiInboxSelected") || 0);
        if (!conversationId) {
            partnerStatus.textContent = "لم يتم اختيار محادثة";
            partnerLink.removeAttribute("href");
            partnerLink.classList.add("is-hidden");
            return;
        }

        const now = Date.now();
        if (!force && conversationId === lastConversationId && now - lastFetchAt < 30000) return;
        lastConversationId = conversationId;
        lastFetchAt = now;

        try {
            const response = await fetch(`/wati/inbox/data?conversation_id=${conversationId}`, {
                credentials: "same-origin",
                headers: { Accept: "application/json" },
                cache: "no-store",
            });
            if (!response.ok) return;
            const payload = await response.json();
            if (!payload.ok || !Array.isArray(payload.conversations)) return;

            const conversation = payload.conversations.find(
                (item) => Number(item.id) === conversationId
            );
            if (!conversation) return;

            if (conversation.partner_id && conversation.partner_url) {
                partnerStatus.textContent = conversation.partner_name
                    ? `مربوط بـ ${conversation.partner_name}`
                    : "مربوط بعميل Odoo";
                partnerLink.href = conversation.partner_url;
                partnerLink.classList.remove("is-hidden");
            } else {
                renderUnlinked();
            }

            if (
                conversation.partner_name &&
                conversation.wati_name &&
                conversation.partner_name !== conversation.wati_name
            ) {
                chatNumber.textContent = `${conversation.wa_id || ""} · WATI: ${conversation.wati_name}`;
            }
        } catch (error) {
            console.debug("WATI partner enhancement unavailable", error);
        }
    }

    refreshPartnerInfo(true);
    window.setInterval(() => refreshPartnerInfo(false), 1000);
    document.addEventListener("click", () => window.setTimeout(() => refreshPartnerInfo(false), 60));
    document.addEventListener("visibilitychange", () => {
        if (!document.hidden) refreshPartnerInfo(true);
    });
})();
