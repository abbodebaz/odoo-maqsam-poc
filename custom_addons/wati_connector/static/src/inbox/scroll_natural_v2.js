(() => {
    "use strict";

    try {
        const messageList = document.getElementById("messageList");
        const conversationList = document.getElementById("conversationList");
        const messageForm = document.getElementById("messageForm");
        if (!messageList || !conversationList) return;

        let pinnedToBottom = true;
        let userInteracting = false;
        let interactionTimer = null;

        function distanceFromBottom() {
            return Math.max(0, messageList.scrollHeight - messageList.scrollTop - messageList.clientHeight);
        }

        function pinNow() {
            if (!pinnedToBottom) return;
            messageList.scrollTop = messageList.scrollHeight;
        }

        function finishUserInteraction() {
            window.clearTimeout(interactionTimer);
            interactionTimer = window.setTimeout(() => {
                userInteracting = false;
                pinnedToBottom = distanceFromBottom() <= 100;
            }, 80);
        }

        function beginUserInteraction() {
            userInteracting = true;
            window.clearTimeout(interactionTimer);
        }

        messageList.addEventListener("wheel", (event) => {
            beginUserInteraction();
            if (event.deltaY < 0) pinnedToBottom = false;
            finishUserInteraction();
        }, { passive: true });

        messageList.addEventListener("touchstart", beginUserInteraction, { passive: true });
        messageList.addEventListener("touchmove", () => {
            if (distanceFromBottom() > 100) pinnedToBottom = false;
        }, { passive: true });
        messageList.addEventListener("touchend", finishUserInteraction, { passive: true });

        messageList.addEventListener("pointerdown", beginUserInteraction, { passive: true });
        messageList.addEventListener("pointerup", finishUserInteraction, { passive: true });

        messageList.addEventListener("scroll", () => {
            if (!userInteracting) return;
            pinnedToBottom = distanceFromBottom() <= 100;
        }, { passive: true });

        // MutationObserver callbacks run before the browser paints. Keeping the
        // scroll position here avoids the visible "jump up, then down" effect
        // when the base inbox refreshes its message DOM.
        const mutationObserver = new MutationObserver(() => {
            if (pinnedToBottom && !userInteracting) pinNow();
        });
        mutationObserver.observe(messageList, { childList: true, subtree: true });

        // Images, video metadata, audio controls and document previews can alter
        // the chat height after the DOM mutation. ResizeObserver keeps the user
        // at the newest message without timers or visible corrective scrolling.
        if (typeof ResizeObserver !== "undefined") {
            const resizeObserver = new ResizeObserver(() => {
                if (pinnedToBottom && !userInteracting) pinNow();
            });
            resizeObserver.observe(messageList);
        }

        conversationList.addEventListener("click", (event) => {
            if (!event.target.closest(".wati-conversation")) return;
            pinnedToBottom = true;
            userInteracting = false;
            queueMicrotask(pinNow);
        }, true);

        document.addEventListener("click", (event) => {
            if (!event.target.closest(".wati-scroll-bottom")) return;
            pinnedToBottom = true;
            userInteracting = false;
            queueMicrotask(pinNow);
        }, true);

        if (messageForm) {
            messageForm.addEventListener("submit", () => {
                pinnedToBottom = true;
                userInteracting = false;
                queueMicrotask(pinNow);
            }, true);
        }

        // Initial conversation load should always open at the latest message.
        queueMicrotask(pinNow);
    } catch (error) {
        console.error("WATI natural scroll enhancement disabled safely", error);
    }
})();
