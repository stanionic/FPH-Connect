(() => {
    let accessToken = null;
    const loginForm = document.querySelector("#loginForm");
    const authMessage = document.querySelector("#authMessage");
    const accountDetails = document.querySelector("#accountDetails");
    const logoutButton = document.querySelector("#logoutButton");
    const changePasswordForm = document.querySelector("#changePasswordForm");

    function messageText(data) {
        const detail = data && data.detail;
        if (typeof detail === "string") return detail;
        if (Array.isArray(detail)) return detail.map(item => item.msg).filter(Boolean).join(" ");
        return "Une erreur est survenue. Veuillez réessayer.";
    }

    async function api(path, options = {}) {
        const headers = { Accept: "application/json", ...(options.headers || {}) };
        if (accessToken) headers.Authorization = `Bearer ${accessToken}`;
        if (options.body) headers["Content-Type"] = "application/json";
        const response = await fetch(path, { ...options, headers, cache: "no-store" });
        let data = null;
        if (response.status !== 204) {
            try {
                data = await response.json();
            } catch {
                throw new Error("Le serveur a renvoyé une réponse invalide. Veuillez réessayer.");
            }
        }
        if (!response.ok) throw new Error(messageText(data));
        return data;
    }

    function setAuthMessage(text, success = false) {
        authMessage.textContent = text;
        authMessage.classList.toggle("success", success);
    }

    function showAccount(user) {
        loginForm.hidden = true;
        accountDetails.hidden = false;
        logoutButton.hidden = false;
        document.querySelector("#accountHeading").textContent = "Votre espace";
        document.querySelector("#welcomeMessage").textContent = `Bonjour ${user.full_name}.`;
        changePasswordForm.hidden = !user.must_change_password;
        if (user.must_change_password) {
            setAuthMessage("Pour protéger votre compte, changez votre mot de passe avant de continuer.");
        } else {
            setAuthMessage("");
        }
    }

    function showLoggedOut() {
        accessToken = null;
        loginForm.hidden = false;
        accountDetails.hidden = true;
        logoutButton.hidden = true;
        changePasswordForm.hidden = true;
        changePasswordForm.reset();
        document.querySelector("#accountHeading").textContent = "Connexion";
        document.querySelector("#password").value = "";
    }

    function appendText(parent, tag, text, className) {
        const element = document.createElement(tag);
        element.textContent = text || "";
        if (className) element.className = className;
        parent.append(element);
        return element;
    }

    function renderChurches(churches) {
        const list = document.querySelector("#churchList");
        list.replaceChildren();
        for (const church of churches) {
            const card = document.createElement("article");
            card.className = "data-card";
            appendText(card, "h3", church.official_name);
            appendText(card, "p", [church.commune, church.department].filter(Boolean).join(", "));
            if (church.address) appendText(card, "p", church.address);
            if (church.contact_phone) appendText(card, "p", church.contact_phone);
            list.append(card);
        }
        document.querySelector("#churchStatus").textContent =
            churches.length ? `${churches.length} église(s) affichée(s).` : "Aucune église trouvée.";
    }

    function renderEvents(events) {
        const list = document.querySelector("#eventList");
        list.replaceChildren();
        for (const event of events) {
            const card = document.createElement("article");
            card.className = "data-card";
            appendText(card, "h3", event.title);
            const start = new Date(event.starts_at);
            appendText(card, "p", Number.isNaN(start.getTime())
                ? event.starts_at
                : new Intl.DateTimeFormat("fr-HT", { dateStyle: "long", timeStyle: "short" }).format(start));
            if (event.location) appendText(card, "p", event.location);
            if (event.department) appendText(card, "p", event.department);
            if (event.description) appendText(card, "p", event.description);
            list.append(card);
        }
        document.querySelector("#eventStatus").textContent =
            events.length ? `${events.length} événement(s) publié(s).` : "Aucun événement publié pour le moment.";
    }

    async function loadChurches(query = "") {
        const status = document.querySelector("#churchStatus");
        status.textContent = "Chargement de l'annuaire…";
        try {
            const params = new URLSearchParams(query);
            const data = await api(`/api/churches?${params}`);
            renderChurches(data);
        } catch (error) {
            status.textContent = error.message;
        }
    }

    async function loadEvents() {
        const status = document.querySelector("#eventStatus");
        status.textContent = "Chargement des événements…";
        try {
            renderEvents(await api("/api/events"));
        } catch (error) {
            status.textContent = error.message;
        }
    }

    loginForm.addEventListener("submit", async event => {
        event.preventDefault();
        setAuthMessage("");
        const submit = loginForm.querySelector("button[type=submit]");
        submit.disabled = true;
        try {
            const result = await api("/api/login", {
                method: "POST",
                body: JSON.stringify({
                    identifier: document.querySelector("#identifier").value.trim(),
                    password: document.querySelector("#password").value,
                }),
            });
            accessToken = result.access_token;
            showAccount(await api("/api/me"));
        } catch (error) {
            accessToken = null;
            setAuthMessage(error.message);
        } finally {
            submit.disabled = false;
        }
    });

    logoutButton.addEventListener("click", async () => {
        let logoutError = null;
        try {
            await api("/api/logout", { method: "POST" });
        } catch (error) {
            logoutError = error.message;
        }
        showLoggedOut();
        if (logoutError) {
            setAuthMessage(`Session fermée sur cet appareil, mais la déconnexion du serveur n'a pas été confirmée : ${logoutError}`);
        } else {
            setAuthMessage("Vous êtes déconnecté.", true);
        }
    });

    changePasswordForm.addEventListener("submit", async event => {
        event.preventDefault();
        const submit = changePasswordForm.querySelector("button[type=submit]");
        submit.disabled = true;
        try {
            await api("/api/change-password", {
                method: "POST",
                body: JSON.stringify({
                    current_password: document.querySelector("#currentPassword").value,
                    new_password: document.querySelector("#newPassword").value,
                }),
            });
            changePasswordForm.reset();
            showAccount(await api("/api/me"));
            setAuthMessage("Mot de passe mis à jour.", true);
        } catch (error) {
            setAuthMessage(error.message);
        } finally {
            submit.disabled = false;
        }
    });

    document.querySelector("#churchSearch").addEventListener("submit", event => {
        event.preventDefault();
        const form = new FormData(event.currentTarget);
        loadChurches({ q: form.get("q"), department: form.get("department") });
    });

    function updateConnection() {
        const online = navigator.onLine;
        document.querySelector("#connectionStatus").textContent = online ? "En ligne" : "Hors ligne";
        document.querySelector("#connectionStatus").classList.toggle("offline", !online);
        document.querySelector("#offlineNotice").hidden = online;
    }
    window.addEventListener("online", updateConnection);
    window.addEventListener("offline", updateConnection);
    updateConnection();
    loadChurches();
    loadEvents();

    if ("serviceWorker" in navigator) {
        window.addEventListener("load", () => {
            navigator.serviceWorker.register("/service-worker.js").catch(error => {
                console.error("Service worker registration failed.", error);
            });
        });
    }
})();
