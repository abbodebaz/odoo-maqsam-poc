(() => {
    "use strict";

    try {
        const messageList = document.getElementById("messageList");
        const conversationList = document.getElementById("conversationList");
        if (!messageList || !conversationList) return;

        let pinnedToBottom = true;
        let lastUserInputAt = 0;
        let programmaticUntil = 0;
        let scheduled = [];

        function distanceFromBottom() {
            return Math.max(0, messageList.scrollHeight - messageList.scrollTop - messageList.clientHeight);
        }

        function markUserInput() {
            lastUserInputAt = performance.now();
        }

        function userRecentlyInteracted() {
            return performance.now() - lastUserInputAt < 700;
        }

        function setPinnedFromCurrentPosition() {
            if (!userRecentlyInteracted()) return;
            pinnedToBottom = distanceFromBottom() <= 130;
        }

        function scrollBottomNow() {
            if (!pinnedToBottom) return;
            programmaticUntil = performance.now() + 120;
            messageList.scrollTop = messageList.scrollHeight;
        }

        function scheduleBottom() {
            if (!pinnedToBottom) return;
            scheduled.forEach((timer) => window.clearTimeout(timer));
            scheduled = [0, 50, 140, 320, 700].map((delay) => window.setTimeout(scrollBottomNow, delay));
        }

        messageList.addEventListener("wheel", () => {
            markUserInput();
            window.requestAnimationFrame(setPinnedFromCurrentPosition);
        }, { passive: true });

        messageList.addEventListener("touchstart", markUserInput, { passive: true });
        messageList.addEventListener("touchmove", markUserInput, { passive: true });
        messageList.addEventListener("touchend", () => {
            markUserInput();
            window.requestAnimationFrame(setPinnedFromCurrentPosition);
        }, { passive: true });

        messageList.addEventListener("pointerdown", markUserInput, { passive: true });
        messageList.addEventListener("pointerup", () => {
            markUserInput();
            window.requestAnimationFrame(setPinnedFromCurrentPosition);
        }, { passive: true });

        messageList.addEventListener("scroll", () => {
            if (performance.now() < programmaticUntil) return;
            setPinnedFromCurrentPosition();
        }, { passive: true });

        // Media changes the content height after the base renderer has already
        // scrolled to the bottom. Keep the user pinned only when they were
        // already reading the latest messages.
        messageList.addEventListener("load", scheduleBottom, true);
        messageList.addEventListener("loadedmetadata", scheduleBottom, true);
        messageList.addEventListener("loadeddata", scheduleBottom, true);

        const observer = new MutationObserver(() => {
            if (pinnedToBottom) scheduleBottom();
        });
        observer.observe(messageList, { childList: true, subtree: true });

        // Opening another conversation should start at the newest message.
        conversationList.addEventListener("click", (event) => {
            if (!event.target.closest(".wati-conversation")) return;
            pinnedToBottom = true;
            scheduleBottom();
        }, true);

        // Respect the polished down-arrow button if present.
        document.addEventListener("click", (event) => {
            if (!event.target.closest(".wati-scroll-bottom")) return;
            pinnedToBottom = true;
            scheduleBottom();
        }, true);

        // Sending a message is an explicit intent to see the latest messages.
        const form = document.getElementById("messageForm");
        if (form) {
            form.addEventListener("submit", () => {
                pinnedToBottom = true;
                scheduleBottom();
            }, true);
        }

        scheduleBottom();
    } catch (error) {
        console.error("WATI scroll stability failed safely", error);
    }
})();
