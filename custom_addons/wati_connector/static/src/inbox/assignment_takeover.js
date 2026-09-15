(() => {
    "use strict";

    const app = document.getElementById("watiInboxApp");
    const badge = document.getElementById("assignmentBadge");
    const statusValue = document.getElementById("drawerAssignmentStatus");
    const assignedUserValue = document.getElementById("drawerAssignedUser");
    const actionBox = document.getElementById("drawerAssignmentAction");
    const messageInput = document.getElementById("messageInput");
    const sendButton = document.getElementById("sendButton");
    const refreshButton = document.getElementById("refreshButton");
    if (!app || !badge || !statusValue || !assignedUserValue || !actionBox) return;

    const csrfToken = app.dataset.csrf || "";
    let lastConversationId = 0;
    let busy = false;

    function selectedId() {
        return Number(localStorage.getItem("watiInboxSelected") || 0);
    }

    function setComposerEnabled(enabled, note) {
        if (messageInput) {
            messageInput.disabled = !enabled;
            messageInput.placeholder = enabled ? "Write a message..." : (note || "Receive the conversation first...");
            messageInput.setAttribute("aria-disabled", enabled ? "false" : "true");
        }
        if (sendButton) {
            sendButton.disabled = !enabled;
            sendButton.setAttribute("aria-disabled", enabled ? "false" : "true");
        }
    }

    function setBadge(text, variant = "unassigned", title = "") {
        badge.textContent = text;
        badge.className = `wati-assignment-badge is-${variant}`;
        badge.title = title || text;
    }

    function makeActionButton(text, onClick, variant = "primary", disabled = false) {
        const button = document.createElement("button");
        button.type = "button";
        button.textContent = text;
        button.disabled = disabled;
        button.className = variant === "takeover"
            ? "wati-actions-secondary is-takeover"
            : (variant === "secondary" ? "wati-actions-secondary" : "wati-actions-primary");
        if (onClick && !disabled) button.addEventListener("click", onClick);
        return button;
    }

    function refreshInboxData() {
        if (refreshButton && !refreshButton.disabled) refreshButton.click();
    }

    function renderEmptyState() {
        setBadge("Choose a conversation", "unassigned");
        statusValue.textContent = "No conversation selected";
        assignedUserValue.textContent = "—";
        actionBox.replaceChildren();
        setComposerEnabled(false, "Choose a conversation first...");
    }

    async function assignMe(force = false, previousUserName = "") {
        const id = selectedId();
        if (!id || busy) return;

        if (force) {
            const confirmed = window.confirm(
                `The conversation is currently at ${previousUserName || "Another employee"}.\n\nDo you want it transferred to you?`
            );
            if (!confirmed) return;
        }

        busy = true;
        actionBox.classList.add("is-busy");
        const currentButton = actionBox.querySelector("button");
        if (currentButton) currentButton.disabled = true;
        try {
            const body = new URLSearchParams({
                csrf_token: csrfToken,
                conversation_id: String(id),
                force: force ? "1" : "0",
            });
            const response = await fetch("/wati/inbox/assign-me", {
                method: "POST",
                credentials: "same-origin",
                headers: {
                    "Content-Type": "application/x-www-form-urlencoded;charset=UTF-8",
                    Accept: "application/json",
                },
                body: body.toString(),
            });
            const payload = await response.json().catch(() => ({}));
            if (!response.ok || !payload.ok) throw new Error(payload.message || "Could not receive the conversation");

            await refreshAssignment(true);
            setComposerEnabled(true);
            refreshInboxData();
            window.setTimeout(refreshInboxData, 500);
            if (messageInput) window.setTimeout(() => messageInput.focus(), 80);
        } catch (error) {
            window.alert(error.message || "Could not receive the conversation.");
            await refreshAssignment(true);
        } finally {
            busy = false;
            actionBox.classList.remove("is-busy");
        }
    }

    function renderAssignment(data) {
        actionBox.replaceChildren();

        if (!data.wati_email) {
            setBadge("Setup required", "warning", "Add WATI Operator Email For the user account");
            statusValue.textContent = "Mail WATI Not set";
            assignedUserValue.textContent = data.current_user_name || "—";
            actionBox.appendChild(makeActionButton("Add mail WATI For the user account", null, "secondary", true));
            setComposerEnabled(false, "Add WATI Operator Email In the user account...");
            return;
        }

        if (data.assigned_to_me) {
            setBadge("✓ Supported by me", "mine", `The conversation is assigned to ${data.current_user_name || "Your account"}`);
            statusValue.textContent = "assigned to you";
            assignedUserValue.textContent = data.current_user_name || "—";
            setComposerEnabled(true);
            return;
        }

        if (data.is_unassigned) {
            setBadge("Not supported", "unassigned");
            statusValue.textContent = "Not supported";
            assignedUserValue.textContent = "—";
            actionBox.appendChild(makeActionButton("Receive the conversation", () => assignMe(false)));
            setComposerEnabled(false, "Receive the conversation first...");
            return;
        }

        setBadge("Assigned to an employee", "other", `Conversation at ${data.assigned_user_name || "Another employee"}`);
        statusValue.textContent = "Assigned to another employee";
        assignedUserValue.textContent = data.assigned_user_name || "—";
        if (data.can_takeover) {
            actionBox.appendChild(
                makeActionButton(
                    "Transfer the conversation to me",
                    () => assignMe(true, data.assigned_user_name),
                    "takeover"
                )
            );
        }
        setComposerEnabled(false, `Conversation at ${data.assigned_user_name || "Another employee"}`);
    }

    async function refreshAssignment(forceRender = false) {
        const id = selectedId();
        if (!id) {
            renderEmptyState();
            lastConversationId = 0;
            return;
        }
        try {
            const response = await fetch(`/wati/inbox/assignment?conversation_id=${encodeURIComponent(id)}`, {
                credentials: "same-origin",
                headers: { Accept: "application/json" },
                cache: "no-store",
            });
            if (!response.ok) return;
            const data = await response.json();
            if (!data.ok) return;

            const signature = JSON.stringify([
                data.assigned_user_id,
                data.assigned_to_me,
                data.wati_email,
                data.can_takeover,
                data.assigned_user_name,
                data.current_user_name,
            ]);
            if (forceRender || lastConversationId !== id || badge.dataset.state !== signature) {
                lastConversationId = id;
                badge.dataset.state = signature;
                renderAssignment(data);
            }
        } catch (error) {
            console.error("WATI assignment state error", error);
        }
    }

    window.setInterval(refreshAssignment, 2500);
    window.addEventListener("storage", refreshAssignment);
    document.addEventListener("click", () => window.setTimeout(refreshAssignment, 50));
    refreshAssignment(true);
})();
