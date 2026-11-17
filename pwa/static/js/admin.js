(() => {
    "use strict";

    const TOKEN_KEY = "fph_token";
    const DEPARTMENTS = ["Ouest", "Nord", "Nord-Est", "Nord-Ouest", "Artibonite", "Centre",
        "Sud", "Sud-Est", "Grand'Anse", "Nippes", "La Diaspora"];
    const LEADER_FUNCTIONS = [
        ["pasteur_principal", "Pasteur principal"],
        ["pasteur_assistant", "Pasteur assistant"],
        ["responsable_principal", "Responsable principal"],
        ["president", "Président"],
        ["secretaire", "Secrétaire"],
        ["tresorier", "Trésorier"],
        ["responsable_service", "Responsable de service"],
        ["autre", "Autre"],
    ];

    const token = sessionStorage.getItem(TOKEN_KEY);
    const state = {
        users: [], churches: [], events: [], meols: [], roles: [], organizations: [],
    };

    const $ = selector => document.querySelector(selector);

    function messageText(data) {
        const detail = data && data.detail;
        if (typeof detail === "string") return detail;
        if (Array.isArray(detail)) return detail.map(item => item.msg).filter(Boolean).join(" ");
        return "Une erreur est survenue. Veuillez réessayer.";
    }

    async function api(path, options = {}) {
        const headers = { Accept: "application/json", ...(options.headers || {}) };
        if (token) headers.Authorization = `Bearer ${token}`;
        if (options.body) headers["Content-Type"] = "application/json";
        const response = await fetch(path, { ...options, headers, cache: "no-store" });
        let data = null;
        if (response.status !== 204) {
            try { data = await response.json(); } catch { data = null; }
        }
        if (!response.ok) throw new Error(messageText(data));
        return data;
    }

    function setStatus(selector, text, success = false) {
        const node = $(selector);
        if (!node) return;
        node.textContent = text;
        node.classList.toggle("success", Boolean(success));
    }

    function values(form) {
        const result = {};
        for (const [key, value] of new FormData(form).entries()) result[key] = value;
        return result;
    }

    function optional(value) {
        const text = (value || "").trim();
        return text ? text : null;
    }

    function emptyState(text) {
        const p = document.createElement("p");
        p.className = "empty-state-inline";
        p.textContent = text;
        return p;
    }

    function card(title, lines, actions) {
        const article = document.createElement("article");
        article.className = "data-card";
        const heading = document.createElement("h3");
        heading.textContent = title;
        article.append(heading);
        for (const [label, value] of lines) {
            if (value === undefined || value === null || value === "") continue;
            const p = document.createElement("p");
            p.textContent = label ? `${label} : ${value}` : value;
            article.append(p);
        }
        const bar = document.createElement("div");
        bar.className = "admin-card-actions";
        for (const action of actions) {
            const button = document.createElement("button");
            button.type = "button";
            button.className = `button${action.secondary ? " button-secondary" : ""}`;
            button.textContent = action.label;
            button.addEventListener("click", action.onClick);
            bar.append(button);
        }
        article.append(bar);
        return article;
    }

    function fillSelect(select, options, emptyLabel = null) {
        select.replaceChildren();
        if (emptyLabel !== null) {
            const option = document.createElement("option");
            option.value = "";
            option.textContent = emptyLabel;
            select.append(option);
        }
        for (const item of options) {
            const option = document.createElement("option");
            option.value = item.value;
            option.textContent = item.label;
            select.append(option);
        }
    }

    // ------------------------------------------------------------------ tabs

    function activateTab(name) {
        document.querySelectorAll(".admin-tab").forEach(tab => {
            tab.classList.toggle("is-active", tab.dataset.tab === name);
            tab.setAttribute("aria-selected", tab.dataset.tab === name ? "true" : "false");
        });
        document.querySelectorAll(".admin-panel").forEach(panel => {
            panel.hidden = panel.id !== `tab-${name}`;
        });
    }

    document.querySelectorAll(".admin-tab").forEach(tab => {
        tab.addEventListener("click", () => activateTab(tab.dataset.tab));
    });

    // ------------------------------------------------------------------ refs

    async function loadReferences() {
        const [roles, churches, organizations] = await Promise.all([
            api("/api/admin/roles"),
            api("/api/admin/churches?limit=200"),
            api("/api/admin/organizations"),
        ]);
        state.roles = roles || [];
        state.churches = churches || [];
        state.organizations = organizations || [];

        fillSelect($("#userRole"), state.roles.map(role => ({
            value: role.code,
            label: `${role.label} (${role.code})`,
        })));
        fillSelect($("#userChurch"), state.churches.map(church => ({
            value: church.id,
            label: church.official_name,
        })), "— Aucune —");
        fillSelect($("#userOrg"), state.organizations.map(org => ({
            value: org.id,
            label: `${org.name} (${org.org_type})`,
        })), "— Aucune —");
    }

    function fillDepartmentSelect(select, emptyLabel) {
        fillSelect(select, DEPARTMENTS.map(department => ({ value: department, label: department })), emptyLabel);
    }

    // ------------------------------------------------------------------ users

    function userActions(user) {
        const actions = [{ label: "Modifier", onClick: () => fillUser(user) }];
        actions.push(user.is_active
            ? { label: "Archiver", secondary: true, onClick: () => archiveUser(user) }
            : { label: "Réactiver", onClick: () => activateUser(user) });
        return actions;
    }

    function permissionLabel(user) {
        const permissions = user.permissions || [];
        if (permissions.includes("document:share")) {
            return (user.extra_permissions || []).includes("document:share")
                ? "partage accordé par le SuperAdmin"
                : "partage autorisé par le rôle";
        }
        return "partage non autorisé";
    }

    function renderUsers() {
        const box = $("#userList");
        box.replaceChildren();
        if (!state.users.length) {
            box.append(emptyState("Aucun utilisateur."));
            return;
        }
        for (const user of state.users) {
            box.append(card(user.full_name, [
                ["E-mail", user.email],
                ["Pseudo", user.username || "—"],
                ["Rôle", user.role],
                ["Département", user.department || "—"],
                ["Actif", user.is_active ? "oui" : "non"],
                ["Partage de fichiers", permissionLabel(user)],
            ], userActions(user)));
        }
    }

    async function loadUsers() {
        setStatus("#userStatus", "Chargement…");
        try {
            state.users = await api("/api/admin/users?limit=200");
            renderUsers();
            setStatus("#userStatus", `${state.users.length} utilisateur(s).`);
        } catch (error) {
            setStatus("#userStatus", error.message);
        }
    }

    function resetUserForm() {
        const form = $("#userForm");
        form.reset();
        form.dataset.mode = "create";
        form.elements.id.value = "";
        form.elements.email.disabled = false;
        form.elements.username.disabled = false;
        form.elements.password.required = true;
        form.querySelectorAll("input[name=extra_permissions]").forEach(box => { box.checked = false; });
        form.querySelector("button[type=submit]").textContent = "Créer l'utilisateur";
        $("#userPasswordHint").textContent = "Obligatoire à la création ; en modification, remplir pour réinitialiser.";
    }

    function fillUser(user) {
        const form = $("#userForm");
        form.dataset.mode = "update";
        form.elements.id.value = user.id;
        form.elements.full_name.value = user.full_name || "";
        form.elements.email.value = user.email || "";
        form.elements.username.value = user.username || "";
        form.elements.password.value = "";
        form.elements.password.required = false;
        form.elements.email.disabled = true;
        form.elements.username.disabled = true;
        form.elements.role_code.value = user.role;
        form.elements.department.value = user.department || "";
        form.elements.church_id.value = user.church_id || "";
        form.elements.organization_id.value = user.organization_id || "";
        form.elements.is_active.checked = Boolean(user.is_active);
        const extras = new Set(user.extra_permissions || []);
        form.querySelectorAll("input[name=extra_permissions]").forEach(box => {
            box.checked = extras.has(box.value);
        });
        form.querySelector("button[type=submit]").textContent = "Enregistrer les modifications";
        $("#userPasswordHint").textContent = "Laisser vide pour conserver le mot de passe ; remplir pour le réinitialiser.";
        form.scrollIntoView({ behavior: "smooth", block: "center" });
    }

    async function archiveUser(user) {
        if (!confirm(`Archiver le compte de ${user.full_name} ? Le compte sera désactivé et ses sessions fermées.`)) return;
        try {
            await api(`/api/admin/users/${encodeURIComponent(user.id)}`, { method: "DELETE" });
            setStatus("#userStatus", "Compte archivé (désactivé).", true);
            await loadUsers();
        } catch (error) {
            setStatus("#userStatus", error.message);
        }
    }

    async function activateUser(user) {
        try {
            await api(`/api/admin/users/${encodeURIComponent(user.id)}/activate`, { method: "POST" });
            setStatus("#userStatus", "Compte réactivé.", true);
            await loadUsers();
        } catch (error) {
            setStatus("#userStatus", error.message);
        }
    }

    // ------------------------------------------------------------------ événements : transitions

    function transitionActions(item) {
        const status = item.validation_status;
        const actions = [];
        const run = (label, action, secondary = false) => actions.push({
            label, secondary,
            onClick: () => transition(item, action),
        });
        if (status === "draft") run("Soumettre", "submit");
        if (status === "pending") run("Approuver", "approve");
        if (status === "approved") run("Publier", "publish");
        if (status === "published") run("Retirer", "withdraw", true);
        if (["draft", "approved", "withdrawn"].includes(status)) run("Archiver", "archive", true);
        return actions;
    }

    async function transition(item, action) {
        const labels = { submit: "soumettre", approve: "approuver", publish: "publier", withdraw: "retirer", archive: "archiver" };
        if (action === "archive" && !confirm(`Archiver « ${item.title} » ?`)) return;
        try {
            await api(`/api/admin/events/${encodeURIComponent(item.id)}/transition`, {
                method: "POST", body: JSON.stringify({ action }),
            });
            setStatus("#eventStatus", `Élément ${labels[action]} avec succès.`, true);
            await loadEvents();
        } catch (error) {
            setStatus("#eventStatus", error.message);
        }
    }

    // ------------------------------------------------------------------ events

    function eventActions(event) {
        return [
            ...(event.validation_status !== "archived" ? [{ label: "Modifier", onClick: () => fillEvent(event) }] : []),
            ...transitionActions(event),
        ];
    }

    function renderEvents() {
        const box = $("#eventList");
        box.replaceChildren();
        if (!state.events.length) {
            box.append(emptyState("Aucun événement."));
            return;
        }
        for (const event of state.events) {
            box.append(card(event.title, [
                ["Début", event.starts_at ? new Date(event.starts_at).toLocaleString("fr-FR") : "—"],
                ["Lieu", event.location || "—"],
                ["Département", event.department || "—"],
                ["Statut", event.validation_status],
            ], eventActions(event)));
        }
    }

    async function loadEvents() {
        setStatus("#eventStatus", "Chargement…");
        try {
            state.events = await api("/api/admin/events?limit=200");
            renderEvents();
            setStatus("#eventStatus", `${state.events.length} événement(s).`);
        } catch (error) {
            setStatus("#eventStatus", error.message);
        }
    }

    function resetEventForm() {
        const form = $("#eventForm");
        form.reset();
        form.dataset.mode = "create";
        form.elements.id.value = "";
        form.elements.version.value = "";
        form.querySelector("button[type=submit]").textContent = "Créer l'événement";
    }

    function localInputValue(iso) {
        if (!iso) return "";
        const date = new Date(iso);
        const pad = value => String(value).padStart(2, "0");
        return `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())}`
            + `T${pad(date.getHours())}:${pad(date.getMinutes())}`;
    }

    function fillEvent(event) {
        const form = $("#eventForm");
        form.dataset.mode = "update";
        form.elements.id.value = event.id;
        form.elements.version.value = event.version;
        form.elements.title.value = event.title || "";
        form.elements.description.value = event.description || "";
        form.elements.starts_at.value = localInputValue(event.starts_at);
        form.elements.ends_at.value = localInputValue(event.ends_at);
        form.elements.location.value = event.location || "";
        form.elements.department.value = event.department || "";
        form.elements.capacity.value = event.capacity || "";
        form.querySelector("button[type=submit]").textContent = "Enregistrer les modifications";
        form.scrollIntoView({ behavior: "smooth", block: "center" });
    }

    // ------------------------------------------------------------------ MEOL

    function meolLines(meol) {
        const lines = [
            ["Catégorie", meol.org_type],
            ["Département", meol.department],
            ["Commune", meol.commune || "—"],
            ["Statut", `${meol.validation_status} / ${meol.affiliation_status}`],
            ["Responsable", meol.leader ? `${meol.leader.full_name} (${meol.leader.function})` : "non renseigné"],
        ];
        if (meol.programs && meol.programs.length) {
            lines.push(["Programmes", meol.programs.map(p => `${p.year} — ${p.title}`).join(" · ")]);
        }
        return lines;
    }

    function meolActions(meol) {
        const actions = [];
        if (meol.validation_status !== "archived") {
            actions.push({ label: "Modifier", onClick: () => fillMeol(meol) });
        }
        if (meol.validation_status === "pending") {
            actions.push({ label: "Approuver", onClick: () => decideMeol(meol, "approve") });
            actions.push({ label: "Rejeter", secondary: true, onClick: () => decideMeol(meol, "reject") });
        }
        if (["draft", "approved", "withdrawn"].includes(meol.validation_status)) {
            actions.push({ label: "Archiver", secondary: true, onClick: () => archiveMeol(meol) });
        }
        return actions;
    }

    function renderMeols() {
        const box = $("#meolList");
        box.replaceChildren();
        if (!state.meols.length) {
            box.append(emptyState("Aucun MEOL pour ce filtre."));
            return;
        }
        for (const meol of state.meols) {
            box.append(card(meol.name, meolLines(meol), meolActions(meol)));
        }
    }

    async function loadMeols() {
        setStatus("#meolStatus", "Chargement…");
        const status = $("#meolFilter").value;
        try {
            state.meols = await api(`/api/admin/meol?status=${encodeURIComponent(status)}`);
            renderMeols();
            setStatus("#meolStatus", `${state.meols.length} MEOL.`);
        } catch (error) {
            setStatus("#meolStatus", error.message);
        }
    }

    async function decideMeol(meol, decision) {
        const verb = decision === "approve" ? "approuver" : "rejeter";
        const reason = prompt(`Motif pour ${verb} « ${meol.name} » (facultatif) :`, "");
        if (reason === null) return;
        try {
            await api(`/api/admin/meol/${encodeURIComponent(meol.id)}/${decision}`, {
                method: "POST", body: JSON.stringify({ reason: reason || null }),
            });
            setStatus("#meolStatus", `MEOL ${decision === "approve" ? "approuvé" : "rejeté"}.`, true);
            await loadMeols();
        } catch (error) {
            setStatus("#meolStatus", error.message);
        }
    }

    async function archiveMeol(meol) {
        if (!confirm(`Archiver le MEOL « ${meol.name} » ?`)) return;
        try {
            await api(`/api/admin/meol/${encodeURIComponent(meol.id)}/archive`, { method: "POST" });
            setStatus("#meolStatus", "MEOL archivé.", true);
            await loadMeols();
        } catch (error) {
            setStatus("#meolStatus", error.message);
        }
    }

    function resetMeolForm() {
        const form = $("#meolForm");
        form.reset();
        form.dataset.mode = "create";
        form.elements.id.value = "";
        form.elements.version.value = "";
        $("#meolLeaderFields").hidden = false;
        $("#meolProgramFields").hidden = false;
        $("#meolProgramForm").hidden = true;
        form.querySelector("button[type=submit]").textContent = "Créer le MEOL";
    }

    function fillMeol(meol) {
        const form = $("#meolForm");
        form.dataset.mode = "update";
        form.elements.id.value = meol.id;
        form.elements.version.value = meol.version;
        form.elements.name.value = meol.name || "";
        form.elements.org_type.value = meol.org_type;
        form.elements.department.value = meol.department || "";
        form.elements.commune.value = meol.commune || "";
        form.elements.address.value = meol.address || "";
        form.elements.contact_email.value = meol.contact_email || "";
        form.elements.contact_phone.value = meol.contact_phone || "";
        $("#meolLeaderFields").hidden = true;
        $("#meolProgramFields").hidden = true;
        $("#meolProgramForm").hidden = false;
        $("#meolProgramForm").elements.id.value = meol.id;
        form.querySelector("button[type=submit]").textContent = "Enregistrer les modifications";
        form.scrollIntoView({ behavior: "smooth", block: "center" });
    }

    function parsePrograms(text) {
        return (text || "").split("\n").map(line => line.trim()).filter(Boolean).map(line => {
            const [year, title, description] = line.split("|").map(part => (part || "").trim());
            return {
                year: Number(year) || new Date().getFullYear(),
                title: title || "Programme",
                description: description || null,
            };
        });
    }

    // ------------------------------------------------------------------ submits

    $("#userForm").addEventListener("submit", async event => {
        event.preventDefault();
        const form = event.currentTarget;
        const data = values(form);
        const editing = form.dataset.mode === "update";
        const payload = {
            full_name: data.full_name,
            role_code: data.role_code,
            department: optional(data.department),
            church_id: optional(data.church_id),
            organization_id: optional(data.organization_id),
            is_active: form.elements.is_active.checked,
            extra_permissions: [...form.querySelectorAll("input[name=extra_permissions]:checked")]
                .map(box => box.value),
        };
        if (data.password) payload.password = data.password;
        if (!editing) {
            if (!data.password || data.password.length < 10) {
                setStatus("#userStatus", "Le mot de passe doit contenir au moins 10 caractères.");
                return;
            }
            payload.email = data.email;
            payload.username = optional(data.username);
        }
        try {
            if (editing) {
                await api(`/api/admin/users/${encodeURIComponent(data.id)}`, {
                    method: "PATCH", body: JSON.stringify(payload),
                });
                setStatus("#userStatus", "Utilisateur mis à jour.", true);
            } else {
                await api("/api/admin/users", { method: "POST", body: JSON.stringify(payload) });
                setStatus("#userStatus", "Utilisateur créé.", true);
            }
            resetUserForm();
            await loadUsers();
            await loadReferences();
        } catch (error) {
            setStatus("#userStatus", error.message);
        }
    });

    function isoOrNull(value) {
        if (!value) return null;
        const date = new Date(value);
        return Number.isNaN(date.getTime()) ? null : date.toISOString();
    }

    $("#eventForm").addEventListener("submit", async event => {
        event.preventDefault();
        const form = event.currentTarget;
        const data = values(form);
        const payload = {
            title: data.title,
            description: optional(data.description),
            starts_at: isoOrNull(data.starts_at),
            ends_at: isoOrNull(data.ends_at),
            location: optional(data.location),
            capacity: data.capacity ? Number(data.capacity) : null,
        };
        try {
            if (form.dataset.mode === "update") {
                payload.version = Number(data.version);
                await api(`/api/admin/events/${encodeURIComponent(data.id)}`, {
                    method: "PATCH", body: JSON.stringify(payload),
                });
                setStatus("#eventStatus", "Événement mis à jour.", true);
            } else {
                payload.department = optional(data.department);
                await api("/api/admin/events", { method: "POST", body: JSON.stringify(payload) });
                setStatus("#eventStatus", "Événement créé.", true);
            }
            resetEventForm();
            await loadEvents();
        } catch (error) {
            setStatus("#eventStatus", error.message);
        }
    });

    $("#meolForm").addEventListener("submit", async event => {
        event.preventDefault();
        const form = event.currentTarget;
        const data = values(form);
        try {
            if (form.dataset.mode === "update") {
                await api(`/api/admin/meol/${encodeURIComponent(data.id)}`, {
                    method: "PATCH",
                    body: JSON.stringify({
                        version: Number(data.version),
                        name: data.name,
                        org_type: data.org_type,
                        department: data.department,
                        commune: optional(data.commune),
                        address: optional(data.address),
                        contact_email: optional(data.contact_email),
                        contact_phone: optional(data.contact_phone),
                    }),
                });
                setStatus("#meolStatus", "MEOL mis à jour.", true);
            } else {
                const leader = {
                    full_name: data.leader_full_name,
                    function: data.leader_function,
                };
                if (optional(data.leader_phone)) leader.professional_phone = optional(data.leader_phone);
                if (optional(data.leader_email)) leader.professional_email = optional(data.leader_email);
                await api("/api/admin/meol/register", {
                    method: "POST",
                    body: JSON.stringify({
                        name: data.name,
                        org_type: data.org_type,
                        department: data.department,
                        commune: optional(data.commune),
                        address: optional(data.address),
                        contact_email: optional(data.contact_email),
                        contact_phone: optional(data.contact_phone),
                        leader,
                        programs: parsePrograms(data.programs),
                    }),
                });
                setStatus("#meolStatus", "MEOL créé. Il est en attente d'approbation.", true);
            }
            resetMeolForm();
            $("#meolFilter").value = "all";
            await loadMeols();
        } catch (error) {
            setStatus("#meolStatus", error.message);
        }
    });

    $("#meolProgramForm").addEventListener("submit", async event => {
        event.preventDefault();
        const form = event.currentTarget;
        const data = values(form);
        try {
            await api(`/api/admin/meol/${encodeURIComponent(data.id)}/programs`, {
                method: "POST",
                body: JSON.stringify({
                    year: Number(data.year),
                    title: data.title,
                    description: optional(data.description),
                }),
            });
            setStatus("#meolStatus", "Programme annuel ajouté.", true);
            form.reset();
            await loadMeols();
        } catch (error) {
            setStatus("#meolStatus", error.message);
        }
    });

    // ------------------------------------------------------------------ wiring

    $("#userCancel").addEventListener("click", resetUserForm);
    $("#eventCancel").addEventListener("click", resetEventForm);
    $("#meolCancel").addEventListener("click", resetMeolForm);
    $("#userRefresh").addEventListener("click", loadUsers);
    $("#eventRefresh").addEventListener("click", loadEvents);
    $("#meolRefresh").addEventListener("click", loadMeols);
    $("#meolFilter").addEventListener("change", loadMeols);

    async function start() {
        fillDepartmentSelect($("#userDepartment"), "— Aucun —");
        fillDepartmentSelect($("#eventDepartment"), "— Aucun —");
        fillDepartmentSelect($("#meolDepartment"), null);
        fillSelect($("#meolLeaderFunction"), LEADER_FUNCTIONS.map(([value, label]) => ({ value, label })));
        resetUserForm();
        resetEventForm();
        resetMeolForm();
        try {
            await loadReferences();
        } catch (error) {
            setStatus("#adminStatus", `Référentiels indisponibles : ${error.message}`);
        }
        await Promise.all([loadUsers(), loadEvents(), loadMeols()]);
        activateTab("users");
    }

    if (!token) {
        setStatus("#adminAuthStatus", "Connectez-vous d'abord sur la page d'accueil : la session de cet onglet a expiré.");
        document.querySelector(".admin-tabs").hidden = true;
        document.querySelectorAll(".admin-panel").forEach(panel => { panel.hidden = true; });
        return;
    }

    api("/api/me").then(user => {
        if (!user || user.role !== "superadmin") {
            setStatus("#adminAuthStatus", "Cette console est réservée au SuperAdministrateur.");
            document.querySelector(".admin-tabs").hidden = true;
            document.querySelectorAll(".admin-panel").forEach(panel => { panel.hidden = true; });
            return;
        }
        setStatus("#adminAuthStatus", `Connecté en tant que ${user.full_name}.`, true);
        start();
    }).catch(error => {
        setStatus("#adminAuthStatus", `Session invalide : ${error.message}. Reconnectez-vous depuis l'accueil.`);
        document.querySelector(".admin-tabs").hidden = true;
        document.querySelectorAll(".admin-panel").forEach(panel => { panel.hidden = true; });
    });
})();
