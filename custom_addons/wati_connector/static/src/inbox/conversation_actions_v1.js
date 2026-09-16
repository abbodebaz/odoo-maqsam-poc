(() => {
    "use strict";

    const trigger = document.getElementById("conversationActionsButton");
    const overlay = document.getElementById("conversationActionsOverlay");
    const closeButton = document.getElementById("conversationActionsClose");
    const phoneValue = document.getElementById("drawerPhone");
    const chatNumber = document.getElementById("chatNumber");
    const buttonsAction = document.getElementById("drawerInteractiveButtons");
    const listAction = document.getElementById("drawerInteractiveList");
    const toast = document.getElementById("watiToast");
    if (!trigger || !overlay || !closeButton) return;

    let toastTimer = null;

    function notify(message, error = false) {
        if (!toast) {
            if (error) window.alert(message);
            return;
        }
        toast.textContent = message;
        toast.classList.toggle("error", error);
        toast.classList.add("show");
        window.clearTimeout(toastTimer);
        toastTimer = window.setTimeout(() => toast.classList.remove("show"), 3200);
    }

    function selectedConversationId() {
        return Number(localStorage.getItem("watiInboxSelected") || 0);
    }

    function syncPhone() {
        if (!phoneValue) return;
        phoneValue.textContent = (chatNumber?.textContent || "").trim() || "Not available";
    }

    function openDrawer() {
        if (!selectedConversationId()) {
            notify("Choose a conversation first.", true);
            return;
        }
        syncPhone();
        overlay.classList.remove("is-hidden");
        overlay.setAttribute("aria-hidden", "false");
        trigger.setAttribute("aria-expanded", "true");
        document.body.classList.add("wati-actions-open");
        window.setTimeout(() => closeButton.focus(), 30);
    }

    function closeDrawer({ restoreFocus = true } = {}) {
        overlay.classList.add("is-hidden");
        overlay.setAttribute("aria-hidden", "true");
        trigger.setAttribute("aria-expanded", "false");
        document.body.classList.remove("wati-actions-open");
        if (restoreFocus) window.setTimeout(() => trigger.focus(), 20);
    }

    function launchInteractive(eventName) {
        closeDrawer({ restoreFocus: false });
        window.setTimeout(() => {
            document.dispatchEvent(new CustomEvent(eventName));
        }, 80);
    }

    trigger.addEventListener("click", openDrawer);
    closeButton.addEventListener("click", () => closeDrawer());
    overlay.addEventListener("click", (event) => {
        if (event.target === overlay) closeDrawer();
    });
    document.addEventListener("keydown", (event) => {
        if (event.key === "Escape" && !overlay.classList.contains("is-hidden")) {
            closeDrawer();
        }
    });
    buttonsAction?.addEventListener("click", () => launchInteractive("wati:open-interactive-buttons"));
    listAction?.addEventListener("click", () => launchInteractive("wati:open-interactive-list"));

    document.addEventListener("click", () => {
        if (!overlay.classList.contains("is-hidden")) syncPhone();
    });
})();
