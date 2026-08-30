(() => {
    "use strict";

    try {
        const app = document.getElementById("watiInboxApp");
        const actions = document.querySelector(".wati-chat-actions");
        if (!app || !actions) return;

        const csrfToken = app.dataset.csrf || "";
        let activeTab = "customer";
        let currentData = null;
        let loading = false;

        function selectedId() {
            return Number(localStorage.getItem("watiInboxSelected") || 0);
        }

        const style = document.createElement("style");
        style.textContent = `
            .wati-context-actions{display:flex;align-items:center;gap:6px;flex-wrap:wrap}
            .wati-context-action{height:36px;border:1px solid #dce4e8;background:#fff;color:#34434d;border-radius:10px;padding:0 11px;font:inherit;font-size:12px;font-weight:750;cursor:pointer;display:inline-flex;align-items:center;gap:6px;transition:.15s ease;white-space:nowrap}
            .wati-context-action:hover{border-color:#9edbb5;background:#f1fbf5;color:#138c43}
            .wati-context-action .count{min-width:18px;height:18px;border-radius:9px;padding:0 5px;background:#edf2f4;color:#64737d;display:inline-flex;align-items:center;justify-content:center;font-size:10px}
            .wati-context-action.has-link{border-color:#bde8cc;background:#f1fbf5;color:#158544}
            .wati-context-backdrop{position:fixed;inset:0;background:rgba(15,23,42,.18);z-index:1490;opacity:0;pointer-events:none;transition:.18s ease}
            .wati-context-backdrop.open{opacity:1;pointer-events:auto}
            .wati-context-drawer{position:fixed;z-index:1500;top:0;bottom:0;left:0;width:min(410px,94vw);background:#fff;box-shadow:18px 0 55px rgba(15,23,42,.16);transform:translateX(-105%);transition:transform .22s ease;display:flex;flex-direction:column;direction:rtl;color:#17222a}
            .wati-context-drawer.open{transform:translateX(0)}
            .wati-context-head{min-height:68px;padding:14px 17px;border-bottom:1px solid #e8edef;display:flex;align-items:center;justify-content:space-between;gap:12px}
            .wati-context-head strong{display:block;font-size:17px}.wati-context-head span{display:block;color:#77858e;font-size:11px;margin-top:2px}
            .wati-context-close{width:36px;height:36px;border:1px solid #dfe6e9;border-radius:10px;background:#fff;cursor:pointer;font-size:20px;color:#53616a}
            .wati-context-tabs{display:grid;grid-template-columns:repeat(3,1fr);gap:6px;padding:10px 12px;border-bottom:1px solid #edf1f2;background:#fbfcfc}
            .wati-context-tab{border:0;border-radius:9px;padding:9px 5px;background:transparent;color:#66757e;font:inherit;font-size:12px;font-weight:750;cursor:pointer}
            .wati-context-tab.active{background:#eaf8ef;color:#128b42}
            .wati-context-body{flex:1;overflow:auto;padding:14px 15px 28px}
            .wati-context-loading{padding:35px 15px;text-align:center;color:#73818a}
            .wati-ctx-card{border:1px solid #e5eaed;border-radius:14px;background:#fff;padding:14px;margin-bottom:10px;box-shadow:0 2px 8px rgba(15,23,42,.025)}
            .wati-ctx-card-title{font-size:14px;font-weight:800;margin-bottom:4px}.wati-ctx-muted{font-size:11px;color:#7b8991;line-height:1.7}
            .wati-ctx-row{display:flex;align-items:center;justify-content:space-between;gap:10px;margin-top:10px}
            .wati-ctx-button,.wati-ctx-link{border:1px solid #d9e3e7;border-radius:10px;background:#fff;color:#33424b;min-height:38px;padding:8px 12px;font:inherit;font-size:12px;font-weight:750;cursor:pointer;text-decoration:none;display:inline-flex;align-items:center;justify-content:center;gap:5px}
            .wati-ctx-button.primary{border-color:#18a951;background:#18a951;color:#fff}.wati-ctx-button.primary:hover{background:#159748}
            .wati-ctx-button.soft{border-color:#bee7cd;background:#effaf3;color:#168846}
            .wati-ctx-section-title{display:flex;align-items:center;justify-content:space-between;gap:10px;margin:3px 0 10px;font-size:14px;font-weight:850}
            .wati-ctx-list{display:flex;flex-direction:column;gap:8px}
            .wati-ctx-item{display:block;border:1px solid #e5eaed;border-radius:12px;padding:11px 12px;text-decoration:none;color:inherit;background:#fff;transition:.15s ease}
            .wati-ctx-item:hover{border-color:#b8dec6;background:#fbfefc}.wati-ctx-item strong{font-size:12px;display:block;margin-bottom:4px}.wati-ctx-item-meta{font-size:10px;color:#7a8890;display:flex;gap:7px;flex-wrap:wrap}
            .wati-ctx-empty{border:1px dashed #dbe4e7;border-radius:13px;padding:22px 12px;text-align:center;color:#7d8a92;font-size:12px;background:#fbfcfc}
            .wati-ctx-form{border:1px solid #dfe7e9;background:#fafcfc;border-radius:13px;padding:12px;margin-bottom:12px;display:none}.wati-ctx-form.open{display:block}
            .wati-ctx-field{margin-bottom:9px}.wati-ctx-field label{display:block;font-size:10px;font-weight:750;color:#64727b;margin-bottom:4px}
            .wati-ctx-field input,.wati-ctx-field textarea,.wati-ctx-field select{width:100%;box-sizing:border-box;border:1px solid #d9e2e6;border-radius:9px;background:#fff;padding:9px 10px;font:inherit;font-size:12px;outline:none}.wati-ctx-field textarea{min-height:74px;resize:vertical}.wati-ctx-field input:focus,.wati-ctx-field textarea:focus{border-color:#6dca91;box-shadow:0 0 0 3px rgba(22,163,74,.08)}
            .wati-ctx-toast{position:fixed;z-index:1600;left:22px;bottom:22px;max-width:340px;background:#17222a;color:#fff;padding:11px 14px;border-radius:11px;font-size:12px;box-shadow:0 10px 30px rgba(15,23,42,.2);opacity:0;transform:translateY(8px);pointer-events:none;transition:.18s ease}.wati-ctx-toast.show{opacity:1;transform:none}.wati-ctx-toast.error{background:#9f1d20}
            @media(max-width:720px){.wati-context-action{width:36px;padding:0;justify-content:center;font-size:0}.wati-context-action .icon{font-size:16px}.wati-context-action .count{position:absolute;margin:-27px 0 0 -24px}.wati-context-drawer{width:100vw}.wati-context-actions{gap:4px}}
        `;
        document.head.appendChild(style);

        const actionBar = document.createElement("div");
        actionBar.className = "wati-context-actions";
        const buttons = {
            customer: makeAction("👤", "العميل"),
            tickets: makeAction("🎫", "التذاكر", true),
            crm: makeAction("💼", "الفرص", true),
        };
        Object.values(buttons).forEach((button) => actionBar.appendChild(button));
        actions.appendChild(actionBar);

        const backdrop = document.createElement("div");
        backdrop.className = "wati-context-backdrop";
        const drawer = document.createElement("aside");
        drawer.className = "wati-context-drawer";
        drawer.innerHTML = `
            <div class="wati-context-head">
                <div><strong id="watiCtxTitle">بيانات العميل</strong><span id="watiCtxSubtitle">WhatsApp × Odoo</span></div>
                <button type="button" class="wati-context-close" aria-label="إغلاق">×</button>
            </div>
            <div class="wati-context-tabs">
                <button type="button" class="wati-context-tab active" data-tab="customer">👤 العميل</button>
                <button type="button" class="wati-context-tab" data-tab="tickets">🎫 التذاكر</button>
                <button type="button" class="wati-context-tab" data-tab="crm">💼 الفرص</button>
            </div>
            <div id="watiCtxBody" class="wati-context-body"></div>
        `;
        const toast = document.createElement("div");
        toast.className = "wati-ctx-toast";
        document.body.append(backdrop, drawer, toast);
        const body = drawer.querySelector("#watiCtxBody");
        const subtitle = drawer.querySelector("#watiCtxSubtitle");
        let toastTimer = null;

        function makeAction(icon, label, count = false) {
            const button = document.createElement("button");
            button.type = "button";
            button.className = "wati-context-action";
            button.innerHTML = `<span class="icon">${icon}</span><span>${label}</span>${count ? '<span class="count">0</span>' : ''}`;
            button.title = label;
            return button;
        }

        function notify(message, error = false) {
            toast.textContent = message || "";
            toast.classList.toggle("error", error);
            toast.classList.add("show");
            clearTimeout(toastTimer);
            toastTimer = setTimeout(() => toast.classList.remove("show"), 3200);
        }

        async function post(url, values) {
            const payload = new URLSearchParams({ csrf_token: csrfToken, ...values });
            const response = await fetch(url, {
                method: "POST",
                credentials: "same-origin",
                headers: { "Content-Type": "application/x-www-form-urlencoded;charset=UTF-8", Accept: "application/json" },
                body: payload.toString(),
            });
            const data = await response.json().catch(() => ({}));
            if (!response.ok || !data.ok) throw new Error(data.message || `تعذر تنفيذ الطلب (${response.status})`);
            return data;
        }

        async function loadContext(force = false) {
            const id = selectedId();
            if (!id || loading) return;
            if (!force && currentData && Number(currentData.conversation?.id) === id) {
                render();
                return;
            }
            loading = true;
            body.innerHTML = '<div class="wati-context-loading">جاري تحميل بيانات العميل...</div>';
            try {
                const response = await fetch(`/wati/inbox/customer-context?conversation_id=${encodeURIComponent(id)}`, {
                    credentials: "same-origin",
                    headers: { Accept: "application/json" },
                    cache: "no-store",
                });
                const data = await response.json().catch(() => ({}));
                if (!response.ok || !data.ok) throw new Error(data.message || "تعذر تحميل البيانات");
                currentData = data;
                updateCounts();
                render();
            } catch (error) {
                body.innerHTML = '<div class="wati-ctx-empty">تعذر تحميل بيانات العميل.</div>';
                notify(error.message, true);
            } finally {
                loading = false;
            }
        }

        function updateCounts() {
            const ticketsCount = buttons.tickets.querySelector(".count");
            const crmCount = buttons.crm.querySelector(".count");
            if (ticketsCount) ticketsCount.textContent = String(currentData?.tickets?.length || 0);
            if (crmCount) crmCount.textContent = String(currentData?.opportunities?.length || 0);
            buttons.customer.classList.toggle("has-link", Boolean(currentData?.partner));
        }

        function render() {
            if (!currentData) return;
            subtitle.textContent = `${currentData.conversation?.name || "WhatsApp"} · ${currentData.conversation?.wa_id || ""}`;
            drawer.querySelectorAll(".wati-context-tab").forEach((tab) => tab.classList.toggle("active", tab.dataset.tab === activeTab));
            if (activeTab === "customer") renderCustomer();
            else if (activeTab === "tickets") renderTickets();
            else renderCrm();
        }

        function renderCustomer() {
            body.replaceChildren();
            if (currentData.partner) {
                const card = document.createElement("div");
                card.className = "wati-ctx-card";
                const title = document.createElement("div");
                title.className = "wati-ctx-card-title";
                title.textContent = currentData.partner.name;
                const meta = document.createElement("div");
                meta.className = "wati-ctx-muted";
                meta.textContent = [currentData.partner.phone, currentData.partner.email].filter(Boolean).join(" · ") || "عميل Odoo مربوط بهذه المحادثة";
                const row = document.createElement("div");
                row.className = "wati-ctx-row";
                const link = document.createElement("a");
                link.className = "wati-ctx-link";
                link.href = currentData.partner.url || "#";
                link.target = "_blank";
                link.rel = "noopener";
                link.textContent = "فتح بطاقة العميل ↗";
                row.appendChild(link);
                card.append(title, meta, row);
                body.appendChild(card);

                const summary = document.createElement("div");
                summary.className = "wati-ctx-card";
                summary.innerHTML = `<div class="wati-ctx-section-title"><span>ملخص العلاقة</span></div><div class="wati-ctx-muted">🎫 ${currentData.tickets?.length || 0} تذكرة · 💼 ${currentData.opportunities?.length || 0} فرصة بيع</div>`;
                body.appendChild(summary);
                return;
            }

            const empty = document.createElement("div");
            empty.className = "wati-ctx-card";
            const title = document.createElement("div");
            title.className = "wati-ctx-card-title";
            title.textContent = "هذا الرقم غير مربوط بعميل Odoo";
            const meta = document.createElement("div");
            meta.className = "wati-ctx-muted";
            meta.textContent = "أنشئ العميل الآن وسيتم أخذ الاسم ورقم WhatsApp تلقائيًا وربط المحادثة به.";
            const form = document.createElement("div");
            form.className = "wati-ctx-form open";
            form.innerHTML = `<div class="wati-ctx-field"><label>اسم العميل</label><input id="watiCtxCustomerName" type="text" /></div><button type="button" class="wati-ctx-button primary" id="watiCtxCreateCustomer">إنشاء وربط العميل</button>`;
            const nameInput = form.querySelector("#watiCtxCustomerName");
            nameInput.value = currentData.conversation?.name || currentData.conversation?.wa_id || "";
            form.querySelector("#watiCtxCreateCustomer").addEventListener("click", async (event) => {
                const button = event.currentTarget;
                button.disabled = true;
                try {
                    const data = await post("/wati/inbox/customer/create", { conversation_id: String(selectedId()), name: nameInput.value.trim() });
                    notify(data.message || "تم إنشاء العميل ✅");
                    currentData = null;
                    await loadContext(true);
                    document.getElementById("refreshButton")?.click();
                } catch (error) { notify(error.message, true); }
                finally { button.disabled = false; }
            });
            empty.append(title, meta, form);
            body.appendChild(empty);
        }

        function renderTickets() {
            body.replaceChildren();
            const heading = document.createElement("div");
            heading.className = "wati-ctx-section-title";
            heading.innerHTML = '<span>تذاكر خدمة العملاء</span><button type="button" class="wati-ctx-button soft">＋ تذكرة جديدة</button>';
            body.appendChild(heading);

            const form = document.createElement("div");
            form.className = "wati-ctx-form";
            form.innerHTML = `
                <div class="wati-ctx-field"><label>الموضوع</label><input id="watiCtxTicketSubject" type="text" /></div>
                <div class="wati-ctx-field"><label>الأولوية</label><select id="watiCtxTicketPriority"><option value="0">عادية</option><option value="1">مهمة</option><option value="2">عاجلة</option></select></div>
                <div class="wati-ctx-field"><label>التفاصيل</label><textarea id="watiCtxTicketDescription"></textarea></div>
                <button type="button" class="wati-ctx-button primary" id="watiCtxCreateTicket">إنشاء التذكرة</button>`;
            body.appendChild(form);
            heading.querySelector("button").addEventListener("click", () => {
                if (!currentData.partner) { activeTab = "customer"; render(); notify("أنشئ العميل أولًا ثم أضف التذكرة.", true); return; }
                form.classList.toggle("open");
                if (form.classList.contains("open")) form.querySelector("input")?.focus();
            });
            form.querySelector("#watiCtxCreateTicket").addEventListener("click", async (event) => {
                const button = event.currentTarget;
                const subject = form.querySelector("#watiCtxTicketSubject").value.trim();
                if (!subject) { notify("اكتب موضوع التذكرة.", true); return; }
                button.disabled = true;
                try {
                    const data = await post("/wati/inbox/ticket/create", {
                        conversation_id: String(selectedId()),
                        subject,
                        priority: form.querySelector("#watiCtxTicketPriority").value,
                        description: form.querySelector("#watiCtxTicketDescription").value.trim(),
                    });
                    notify(data.message || "تم إنشاء التذكرة ✅");
                    currentData = null;
                    await loadContext(true);
                } catch (error) { notify(error.message, true); }
                finally { button.disabled = false; }
            });

            const list = document.createElement("div");
            list.className = "wati-ctx-list";
            const tickets = currentData.tickets || [];
            if (!tickets.length) {
                const empty = document.createElement("div");
                empty.className = "wati-ctx-empty";
                empty.textContent = "لا توجد تذاكر مرتبطة بهذه المحادثة حتى الآن.";
                list.appendChild(empty);
            } else {
                tickets.forEach((ticket) => {
                    const item = document.createElement("a");
                    item.className = "wati-ctx-item";
                    item.href = ticket.url || "#";
                    item.target = "_blank";
                    item.rel = "noopener";
                    const title = document.createElement("strong");
                    title.textContent = `${ticket.name} · ${ticket.subject}`;
                    const meta = document.createElement("div");
                    meta.className = "wati-ctx-item-meta";
                    meta.textContent = [ticket.status_label, ticket.user_name].filter(Boolean).join(" · ");
                    item.append(title, meta);
                    list.appendChild(item);
                });
            }
            body.appendChild(list);
        }

        function renderCrm() {
            body.replaceChildren();
            const heading = document.createElement("div");
            heading.className = "wati-ctx-section-title";
            heading.innerHTML = '<span>فرص CRM</span><button type="button" class="wati-ctx-button soft">＋ فرصة جديدة</button>';
            body.appendChild(heading);

            const form = document.createElement("div");
            form.className = "wati-ctx-form";
            form.innerHTML = `
                <div class="wati-ctx-field"><label>اسم الفرصة</label><input id="watiCtxOpportunityName" type="text" /></div>
                <div class="wati-ctx-field"><label>القيمة المتوقعة (اختياري)</label><input id="watiCtxOpportunityRevenue" type="number" min="0" step="1" /></div>
                <div class="wati-ctx-field"><label>ملاحظة</label><textarea id="watiCtxOpportunityDescription"></textarea></div>
                <button type="button" class="wati-ctx-button primary" id="watiCtxCreateOpportunity">إنشاء فرصة البيع</button>`;
            body.appendChild(form);
            heading.querySelector("button").addEventListener("click", () => {
                if (!currentData.partner) { activeTab = "customer"; render(); notify("أنشئ العميل أولًا ثم أضف فرصة البيع.", true); return; }
                form.classList.toggle("open");
                if (form.classList.contains("open")) form.querySelector("input")?.focus();
            });
            form.querySelector("#watiCtxCreateOpportunity").addEventListener("click", async (event) => {
                const button = event.currentTarget;
                const name = form.querySelector("#watiCtxOpportunityName").value.trim();
                if (!name) { notify("اكتب اسم فرصة البيع.", true); return; }
                button.disabled = true;
                try {
                    const data = await post("/wati/inbox/opportunity/create", {
                        conversation_id: String(selectedId()),
                        name,
                        expected_revenue: form.querySelector("#watiCtxOpportunityRevenue").value || "0",
                        description: form.querySelector("#watiCtxOpportunityDescription").value.trim(),
                    });
                    notify(data.message || "تم إنشاء فرصة البيع ✅");
                    currentData = null;
                    await loadContext(true);
                } catch (error) { notify(error.message, true); }
                finally { button.disabled = false; }
            });

            const list = document.createElement("div");
            list.className = "wati-ctx-list";
            const opportunities = currentData.opportunities || [];
            if (!opportunities.length) {
                const empty = document.createElement("div");
                empty.className = "wati-ctx-empty";
                empty.textContent = currentData.partner ? "لا توجد فرص بيع لهذا العميل حتى الآن." : "اربط المحادثة بعميل Odoo أولًا.";
                list.appendChild(empty);
            } else {
                opportunities.forEach((lead) => {
                    const item = document.createElement("a");
                    item.className = "wati-ctx-item";
                    item.href = lead.url || "#";
                    item.target = "_blank";
                    item.rel = "noopener";
                    const title = document.createElement("strong");
                    title.textContent = lead.name;
                    const meta = document.createElement("div");
                    meta.className = "wati-ctx-item-meta";
                    const parts = [lead.stage_name, lead.user_name];
                    if (Number(lead.expected_revenue || 0) > 0) parts.push(`${Number(lead.expected_revenue).toLocaleString("ar-SA")} ر.س`);
                    meta.textContent = parts.filter(Boolean).join(" · ");
                    item.append(title, meta);
                    list.appendChild(item);
                });
            }
            body.appendChild(list);
        }

        function openDrawer(tab) {
            const id = selectedId();
            if (!id) { notify("اختر محادثة أولًا.", true); return; }
            activeTab = tab;
            backdrop.classList.add("open");
            drawer.classList.add("open");
            loadContext(false);
        }

        function closeDrawer() {
            backdrop.classList.remove("open");
            drawer.classList.remove("open");
        }

        buttons.customer.addEventListener("click", () => openDrawer("customer"));
        buttons.tickets.addEventListener("click", () => openDrawer("tickets"));
        buttons.crm.addEventListener("click", () => openDrawer("crm"));
        backdrop.addEventListener("click", closeDrawer);
        drawer.querySelector(".wati-context-close").addEventListener("click", closeDrawer);
        drawer.querySelectorAll(".wati-context-tab").forEach((tab) => tab.addEventListener("click", () => {
            activeTab = tab.dataset.tab || "customer";
            render();
        }));
        document.addEventListener("keydown", (event) => { if (event.key === "Escape" && drawer.classList.contains("open")) closeDrawer(); });

        document.getElementById("conversationList")?.addEventListener("click", () => {
            currentData = null;
            setTimeout(() => { if (drawer.classList.contains("open")) loadContext(true); }, 180);
        }, true);

        // Preload counts quietly for the selected conversation without changing the UI.
        setTimeout(() => loadContext(true), 900);
    } catch (error) {
        console.error("WATI customer context disabled safely", error);
    }
})();
