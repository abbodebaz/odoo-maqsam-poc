(() => {
    "use strict";

    try {
        const app = document.getElementById("watiInboxApp");
        const filtersWrap = document.querySelector(".wati-filters");
        const conversationList = document.getElementById("conversationList");
        const conversationCount = document.getElementById("conversationCount");
        if (!app || !filtersWrap || !conversationList) return;

        const buttons = Array.from(filtersWrap.querySelectorAll(".wati-filter"));
        let activeFilter = localStorage.getItem("watiInboxFilterV2") || "all";
        let rowsById = new Map();
        let loading = false;
        let lastLoadedAt = 0;

        function setActiveButton() {
            buttons.forEach((button) => {
                button.classList.toggle("active", (button.dataset.filter || "all") === activeFilter);
            });
        }

        function matchesFilter(row) {
            if (!row) return activeFilter === "all";
            if (activeFilter === "mine") return Boolean(row.assigned_to_me);
            if (activeFilter === "unassigned") return Boolean(row.is_unassigned);
            if (activeFilter === "unread") return Number(row.unread_count || 0) > 0;
            return true;
        }

        function applyFilter() {
            const items = Array.from(conversationList.querySelectorAll(".wati-conversation[data-conversation-id]"));
            let visible = 0;
            items.forEach((item) => {
                const id = Number(item.dataset.conversationId || 0);
                const show = matchesFilter(rowsById.get(id));
                item.style.display = show ? "" : "none";
                item.dataset.watiFilterHidden = show ? "0" : "1";
                if (show) visible += 1;
            });

            if (conversationCount && rowsById.size) {
                const label = activeFilter === "all" ? "محادثة" : "مطابقة";
                conversationCount.textContent = `${visible} ${label} من ${rowsById.size}`;
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
                rowsById = new Map(payload.conversations.map((row) => [Number(row.id), row]));
                lastLoadedAt = Date.now();
                applyFilter();
            } catch (error) {
                console.error("WATI filter enhancement error", error);
            } finally {
                loading = false;
            }
        }

        filtersWrap.addEventListener("click", (event) => {
            const button = event.target.closest(".wati-filter");
            if (!button || !filtersWrap.contains(button)) return;

            // Own the filter behavior here so it remains deterministic even if
            // the base inbox renderer is refreshed or enhanced by other layers.
            event.preventDefault();
            event.stopImmediatePropagation();
            activeFilter = button.dataset.filter || "all";
            localStorage.setItem("watiInboxFilterV2", activeFilter);
            setActiveButton();
            loadRows(true);
        }, true);

        const observer = new MutationObserver(() => {
            window.requestAnimationFrame(() => applyFilter());
        });
        observer.observe(conversationList, { childList: true });

        setActiveButton();
        loadRows(true);
        window.setInterval(() => loadRows(false), 4000);
    } catch (error) {
        console.error("WATI filters fix failed safely", error);
    }
})();
