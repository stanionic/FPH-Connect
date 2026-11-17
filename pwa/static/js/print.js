(() => {
    "use strict";

    const TOKEN_KEY = "fph_token";
    const token = (() => {
        try { return sessionStorage.getItem(TOKEN_KEY); } catch { return null; }
    })();

    const $ = selector => document.querySelector(selector);

    function setStatus(text, success = false) {
        const node = $("#printStatus");
        if (!node) return;
        node.textContent = text;
        node.classList.toggle("success", Boolean(success));
    }

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

    function emptyState(text) {
        const p = document.createElement("p");
        p.className = "empty-state-inline";
        p.textContent = text;
        return p;
    }

    function formatDate(iso) {
        if (!iso) return "—";
        const date = new Date(iso);
        if (Number.isNaN(date.getTime())) return iso;
        return new Intl.DateTimeFormat("fr-FR", { dateStyle: "medium", timeStyle: "short" }).format(date);
    }

    function documentCard(doc) {
        const article = document.createElement("article");
        article.className = "data-card";

        const heading = document.createElement("h3");
        heading.textContent = doc.name;
        article.append(heading);

        for (const line of [
            `Format : ${doc.extension.toUpperCase()}`,
            `Taille : ${doc.size_label}`,
            `Modifié le : ${formatDate(doc.modified_at)}`,
        ]) {
            const p = document.createElement("p");
            p.textContent = line;
            article.append(p);
        }

        const actions = document.createElement("div");
        actions.className = "admin-card-actions";
        for (const [label, print] of [["Ouvrir", false], ["Imprimer", true]]) {
            const button = document.createElement("button");
            button.type = "button";
            button.className = `button${print ? "" : " button-secondary"}`;
            button.textContent = label;
            button.addEventListener("click", () => openDocument(doc, print, button));
            actions.append(button);
        }
        article.append(actions);
        return article;
    }

    function render(documents) {
        const box = $("#printList");
        box.replaceChildren();
        if (!documents.length) {
            box.append(emptyState("Aucun document dans le dossier connecté."));
            return;
        }
        for (const doc of documents) box.append(documentCard(doc));
    }

    async function loadDocuments() {
        setStatus("Chargement du dossier connecté…");
        const query = new URLSearchParams({ q: ($("#printQuery").value || "").trim() });
        try {
            const result = await api(`/api/print-folder?${query}`);
            render(result.documents || []);
            const count = result.count || 0;
            setStatus(
                count ? `${count} document(s) disponible(s).` : "Aucun document dans le dossier connecté.",
                count > 0,
            );
        } catch (error) {
            render([]);
            setStatus(error.message);
        }
    }

    async function fetchDocument(doc) {
        const headers = { Accept: "*/*" };
        if (token) headers.Authorization = `Bearer ${token}`;
        const response = await fetch(
            `/api/print-folder/file?name=${encodeURIComponent(doc.name)}`,
            { headers, cache: "no-store" },
        );
        if (!response.ok) {
            let data = null;
            try { data = await response.json(); } catch { data = null; }
            throw new Error(messageText(data));
        }
        return response.blob();
    }

    async function logPrint(doc) {
        try {
            await api(`/api/print-folder/${encodeURIComponent(doc.name)}/print`, {
                method: "POST",
                body: JSON.stringify({ copies: 1 }),
            });
        } catch (error) {
            // Le document reste imprimable : on signale seulement que la trace a échoué.
            setStatus(`Impression lancée, mais le journal n'a pas pu être mis à jour : ${error.message}`);
        }
    }

    async function openDocument(doc, print, button) {
        if (button) button.disabled = true;
        setStatus(print ? `Préparation de « ${doc.name} »…` : `Ouverture de « ${doc.name} »…`);
        let url = null;
        try {
            const blob = await fetchDocument(doc);
            url = URL.createObjectURL(blob);
            const win = window.open(url, "_blank", "noopener");
            if (!win) {
                setStatus("La fenêtre a été bloquée par le navigateur. Autorisez les pop-ups puis réessayez.");
                return;
            }
            if (print) {
                await logPrint(doc);
                const attempt = () => {
                    try { win.focus(); win.print(); } catch { /* le lecteur PDF gère sa propre impression */ }
                };
                try { win.addEventListener("load", attempt, { once: true }); } catch { /* ignore */ }
                setTimeout(attempt, 1200);
                setStatus(`« ${doc.name} » envoyé à la boîte de dialogue d'impression.`, true);
            } else {
                setStatus(`« ${doc.name} » ouvert dans un nouvel onglet.`, true);
            }
        } catch (error) {
            setStatus(error.message);
        } finally {
            if (button) button.disabled = false;
            if (url) setTimeout(() => URL.revokeObjectURL(url), 60000);
        }
    }

    $("#printSearch").addEventListener("submit", event => {
        event.preventDefault();
        loadDocuments();
    });
    $("#printRefresh").addEventListener("click", loadDocuments);

    if (!token) {
        setStatus("Connectez-vous d'abord sur la page d'accueil pour accéder au dossier connecté.");
        return;
    }

    api("/api/me").then(user => {
        setStatus(`Connecté en tant que ${user.full_name}.`, true);
        loadDocuments();
    }).catch(error => {
        $("#printAuthStatus").textContent = `Session invalide : ${error.message}. Reconnectez-vous depuis l'accueil.`;
    });
})();
