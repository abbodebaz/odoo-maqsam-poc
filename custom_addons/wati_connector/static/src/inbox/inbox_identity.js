/* Clear already rendered conversations if the agent identity changes mid-session. */
(() => {
    "use strict";
    const originalFetch = window.fetch.bind(window);
    let blocked = false;
    window.fetch = async (...args) => {
        const response = await originalFetch(...args);
        const url = typeof args[0] === "string" ? args[0] : args[0]?.url || "";
        if (!blocked && /^\/wati\/inbox\/data(?:\?|$)/.test(url)) {
            const payload = await response.clone().json().catch(() => null);
            if (payload?.identity_error) {
                blocked = true;
                const app = document.getElementById("watiInboxApp");
                if (app) {
                    const warning = document.createElement("section");
                    warning.setAttribute("role", "alert");
                    warning.style.cssText = "margin:auto;max-width:650px;padding:40px;text-align:center;background:white;border:1px solid #e2e8f0;border-radius:16px;";
                    const heading = document.createElement("h2");
                    heading.textContent = "WATI Agent verification required";
                    const text = document.createElement("p");
                    text.textContent = payload.identity_error;
                    const retry = document.createElement("a");
                    retry.href = "/wati/inbox";
                    retry.textContent = "Retry after correction";
                    warning.append(heading, text, retry);
                    app.replaceChildren(warning);
                    localStorage.removeItem("watiInboxSelected");
                }
            }
        }
        return response;
    };
})();
