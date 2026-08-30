(() => {
    "use strict";

    try {
        const filtersWrap = document.querySelector(".wati-filters");
        const conversationList = document.getElementById("conversationList");
        const conversationCount = document.getElementById("conversationCount");
        if (!filtersWrap || !conversationList) return;

        const buttons = Array.from(filtersWrap.querySelectorAll(".wati-filter"));
        let activeFilter = localStorage.getItem("watiInboxFilterV3") || "all";
        let rowsById = new Map();
        let currentUserId = 0;
        let loading = false;
        let lastLoadedAt = 0;

        function setActiveButton() {
            buttons.forEach((button) => {
                button.classList.toggle("active", (button.dataset.filter || "all") === activeFilter);
            });
        }

        function assignedToMe(row) {
            if (!row) return false;
            const assignedId = Number(row.assigned_user_id || 0);
            return Boolean(currentUserId && assignedId && assignedId === currentUserId);
        }

        function isUnassigned(row) {
            if (!row) return false;
            return !Number(row.assigned_user_id || 0);
        }

        function matchesFilter(row) {
            if (!row) return activeFilter === "all";
            if (activeFilter === "mine") return assignedToMe(row);
            if (activeFilter === "unassigned") return isUnassigned(row);
            if (activeFilter === "unread") return Number(row.unread_count || 0) > 0;
            return true;
        }

        function applyFilter() {
            const items = Array.from(conversationList.querySelectorAll(".wati-conversation[data-conversation-id]"));
            let visible = 0;

            items.forEach((item) => {
                const id = Number(item.dataset.conversationId || 0);
                const show = matchesFilter(rowsById.get(id));
                if (show) {
                    item.style.removeProperty("display");
                    item.dataset.watiFilterHidden = "0";
                    visible += 1;
                } else {
                    item.style.setProperty("display", "none", "important");
                    item.dataset.watiFilterHidden = "1";
                }
            });

            if (conversationCount && rowsById.size) {
                conversationCount.textContent = activeFilter === "all"
                    ? `${visible} محادثة`
                    : `${visible} مطابقة من ${rowsById.size}`;
            }
            setActiveButton();
        }

        async function loadRows(force = false) {
            const now = Date.now();
            if (loading) return;
            if (!force && now - lastLoadedAt < 1800 && rowsById.size) {
                applyFilter();
                return;
            }

            loading = true;
            try {
                const selectedId = Number(localStorage.getItem("watiInboxSelected") || 0);
                const params = new URLSearchParams();
                if (selectedId) params.set("conversation_id", String(selectedId));

                const response = await fetch(`/wati/inbox/data?${params.toString()}`, {
                    credentials: "same-origin",
                    headers: { Accept: "application/json" },
                    cache: "no-store",
                });
                if (!response.ok) return;

                const payload = await response.json().catch(() => ({}));
                if (!payload.ok || !Array.isArray(payload.conversations)) return;

                currentUserId = Number(payload.current_user_id || 0);
                rowsById = new Map(payload.conversations.map((row) => [Number(row.id), row]));
                lastLoadedAt = Date.now();
                applyFilter();
            } catch (error) {
                console.error("WATI filters v2 error", error);
            } finally {
                loading = false;
            }
        }

        filtersWrap.addEventListener("click", (event) => {
            const button = event.target.closest(".wati-filter");
            if (!button || !filtersWrap.contains(button)) return;

            event.preventDefault();
            event.stopImmediatePropagation();
            activeFilter = button.dataset.filter || "all";
            localStorage.setItem("watiInboxFilterV3", activeFilter);
            setActiveButton();
            loadRows(true);
        }, true);

        const observer = new MutationObserver(() => {
            window.requestAnimationFrame(applyFilter);
        });
        observer.observe(conversationList, { childList: true });

        setActiveButton();
        loadRows(true);
        window.setInterval(() => loadRows(false), 4000);
    } catch (error) {
        console.error("WATI filters v2 failed safely", error);
    }
})();
