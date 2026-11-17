(() => {
    "use strict";

    const TOKEN_KEY = "fph_token";
    const token = (() => {
        try { return sessionStorage.getItem(TOKEN_KEY); } catch { return null; }
    })();

    const $ = selector => document.querySelector(selector);
    const state = { me: null, documents: [], query: "" };

    function setStatus(selector, text, success = false) {
        const node = $(selector);
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

    function hasPermission(code) {
        return Boolean(state.me && (state.me.permissions || []).includes(code));
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

    function formatSize(bytes) {
        const value = Number(bytes) || 0;
        if (value < 1024) return `${value} o`;
        if (value < 1024 * 1024) return `${(value / 1024).toFixed(1)} Ko`;
        return `${(value / (1024 * 1024)).toFixed(1)} Mo`;
    }

    function canRemove(doc) {
        if (!state.me) return false;
        return state.me.role === "superadmin" || doc.uploaded_by === state.me.id;
    }

    function documentCard(doc) {
        const article = document.createElement("article");
        article.className = "data-card";

        const heading = document.createElement("h3");
        heading.textContent = doc.title || doc.original_name;
        article.append(heading);

        if (doc.share_note) {
            const message = document.createElement("p");
            message.className = "share-message";
            message.textContent = `« ${doc.share_note} »`;
            article.append(message);
        }

        for (const line of [
            `Fichier : ${doc.original_name}`,
            `Taille : ${formatSize(doc.size)}`,
            `Partagé le : ${formatDate(doc.created_at)}`,
        ]) {
            const p = document.createElement("p");
            p.textContent = line;
            article.append(p);
        }

        const actions = document.createElement("div");
        actions.className = "admin-card-actions";

        const download = document.createElement("button");
        download.type = "button";
        download.className = "button";
        download.textContent = "Télécharger";
        download.addEventListener("click", () => downloadDocument(doc, download));
        actions.append(download);

        if (canRemove(doc)) {
            const remove = document.createElement("button");
            remove.type = "button";
            remove.className = "button button-secondary";
            remove.textContent = "Retirer du partage";
            remove.addEventListener("click", () => removeDocument(doc, remove));
            actions.append(remove);
        }

        article.append(actions);
        return article;
    }

    function visibleDocuments() {
        const query = state.query.trim().toLowerCase();
        if (!query) return state.documents;
        return state.documents.filter(doc => [doc.title, doc.original_name, doc.share_note]
            .filter(Boolean)
            .some(value => value.toLowerCase().includes(query)));
    }

    function render() {
        const box = $("#docList");
        box.replaceChildren();
        const documents = visibleDocuments();
        if (!documents.length) {
            box.append(emptyState(state.query
                ? "Aucun fichier ne correspond à cette recherche."
                : "Aucun fichier partagé pour le moment."));
            return;
        }
        for (const doc of documents) box.append(documentCard(doc));
    }

    async function loadDocuments() {
        setStatus("#docStatus", "Chargement des fichiers partagés…");
        try {
            state.documents = await api("/api/documents");
            render();
            const count = state.documents.length;
            setStatus("#docStatus",
                count ? `${count} fichier(s) partagé(s) sur le réseau.` : "Aucun fichier partagé pour le moment.",
                count > 0);
        } catch (error) {
            state.documents = [];
            render();
            setStatus("#docStatus", error.message);
        }
    }

    async function downloadDocument(doc, button) {
        if (button) button.disabled = true;
        setStatus("#docStatus", `Téléchargement de « ${doc.original_name} »…`);
        try {
            const response = await fetch(
                `/api/documents/${encodeURIComponent(doc.id)}/download`,
                { headers: { Authorization: `Bearer ${token}` }, cache: "no-store" },
            );
            if (!response.ok) {
                let data = null;
                try { data = await response.json(); } catch { data = null; }
                throw new Error(messageText(data));
            }
            const blob = await response.blob();
            const url = URL.createObjectURL(blob);
            const link = document.createElement("a");
            link.href = url;
            link.download = doc.original_name || "document";
            document.body.append(link);
            link.click();
            link.remove();
            setTimeout(() => URL.revokeObjectURL(url), 30000);
            setStatus("#docStatus", `« ${doc.original_name} » téléchargé.`, true);
        } catch (error) {
            setStatus("#docStatus", error.message);
        } finally {
            if (button) button.disabled = false;
        }
    }

    async function removeDocument(doc, button) {
        if (!confirm(`Retirer « ${doc.title || doc.original_name} » du partage réseau ?`)) return;
        if (button) button.disabled = true;
        try {
            await api(`/api/documents/${encodeURIComponent(doc.id)}`, { method: "DELETE" });
            setStatus("#docStatus", "Fichier retiré du partage.", true);
            await loadDocuments();
        } catch (error) {
            setStatus("#docStatus", error.message);
        } finally {
            if (button) button.disabled = false;
        }
    }

    $("#shareForm").addEventListener("submit", async event => {
        event.preventDefault();
        const form = event.currentTarget;
        const button = form.querySelector("button[type=submit]");
        if (button) button.disabled = true;
        setStatus("#docStatus", "Envoi du fichier…");
        try {
            const response = await fetch("/api/documents/share", {
                method: "POST",
                headers: { Authorization: `Bearer ${token}`, Accept: "application/json" },
                body: new FormData(form),
                cache: "no-store",
            });
            let data = null;
            try { data = await response.json(); } catch { data = null; }
            if (!response.ok) throw new Error(messageText(data));
            form.reset();
            setStatus("#docStatus",
                `« ${data.title || data.original_name} » partagé avec le réseau FPH.`, true);
            await loadDocuments();
        } catch (error) {
            setStatus("#docStatus", error.message);
        } finally {
            if (button) button.disabled = false;
        }
    });

    $("#docSearch").addEventListener("submit", event => {
        event.preventDefault();
        state.query = $("#docQuery").value || "";
        render();
        const shown = visibleDocuments().length;
        setStatus("#docStatus",
            state.query ? `${shown} fichier(s) trouvé(s).` : `${state.documents.length} fichier(s) partagé(s).`,
            shown > 0);
    });

    $("#docRefresh").addEventListener("click", loadDocuments);

    async function start() {
        if (!token) {
            setStatus("#docAuthStatus",
                "Connectez-vous d'abord sur la page d'accueil pour accéder au partage de fichiers.");
            return;
        }
        try {
            state.me = await api("/api/me");
        } catch (error) {
            setStatus("#docAuthStatus",
                `Session invalide : ${error.message}. Reconnectez-vous depuis l'accueil.`);
            return;
        }
        const allowed = hasPermission("document:read") || hasPermission("document:share");
        if (!allowed) {
            setStatus("#docAuthStatus",
                "Le partage de fichiers n'est pas encore autorisé pour votre compte. Demandez au SuperAdmin de vous accorder cette permission.");
            return;
        }
        setStatus("#docAuthStatus", `Connecté en tant que ${state.me.full_name}.`, true);
        if (hasPermission("document:share")) {
            $("#sharePanel").hidden = false;
        } else {
            setStatus("#docAuthStatus",
                `Connecté en tant que ${state.me.full_name}. Vous pouvez consulter les fichiers, mais le partage n'est pas autorisé pour votre compte.`,
                true);
        }
        if (hasPermission("document:read")) {
            await loadDocuments();
        } else {
            $("#docList").replaceChildren(emptyState(
                "Vous pouvez partager des fichiers, mais la consultation du partage n'est pas autorisée."));
        }
    }

    start();
})();
