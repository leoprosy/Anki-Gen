/* ============================================================
   Ankigen — tableau de bord : modale « Nouvelle frise »
   Depuis un texte (titre, langue, texte) ou par import d'un JSON
   (fichier déposé ou collé). Un JSON invalide affiche ses erreurs
   et peut quand même être ouvert pour être corrigé.
   ============================================================ */
(() => {
  const dialog = document.getElementById("tl-new");
  if (!dialog) return;
  const $ = (id) => document.getElementById(id);
  const T = (key, params) => window.T(key, params);
  const escapeHtml = (s) => String(s == null ? "" : s).replace(/[&<>"']/g, (c) => (
    { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));

  const els = {
    open: $("tl-new-open"), close: $("tl-new-close"), cancel: $("tl-new-cancel"),
    tabs: $("tl-new-tabs"), panelText: $("tl-new-text"), panelJson: $("tl-new-json"),
    title: $("tl-new-title-input"), lang: $("tl-new-lang"), text: $("tl-new-text-input"),
    json: $("tl-new-json-input"), drop: $("tl-new-drop"), file: $("tl-new-file"),
    dropLabel: $("tl-new-drop-label"), errors: $("tl-new-errors"),
    create: $("tl-new-create"), force: $("tl-new-force"),
  };
  let tab = "text";

  function setTab(next) {
    tab = next;
    for (const button of els.tabs.querySelectorAll("[data-tab]")) {
      const on = button.dataset.tab === next;
      button.classList.toggle("active", on);
      button.setAttribute("aria-selected", String(on));
      button.tabIndex = on ? 0 : -1;
    }
    els.panelText.hidden = next !== "text";
    els.panelJson.hidden = next !== "json";
    resetErrors();
  }

  function resetErrors() {
    els.errors.innerHTML = "";
    els.force.hidden = true;
  }

  function showErrors(items) {
    els.errors.innerHTML = items.slice(0, 8).map((e) =>
      `<li>${e.path ? `<code>${escapeHtml(e.path)}</code> ` : ""}${escapeHtml(e.message || e)}</li>`).join("")
      + (items.length > 8 ? `<li>${escapeHtml(T("timeline.ui.more_errors", { n: items.length - 8 }))}</li>` : "");
  }

  async function submit(force) {
    resetErrors();
    const body = tab === "text"
      ? { text: els.text.value, title: els.title.value, lang: els.lang.value }
      : { json: els.json.value, force: !!force };
    if (tab === "text" && !els.title.value.trim()) {
      showErrors([T("timeline.ui.title_required")]);
      els.title.focus();
      return;
    }
    if (tab === "json" && !els.json.value.trim()) {
      showErrors([T("timeline.ui.json_required")]);
      els.json.focus();
      return;
    }
    els.create.disabled = true;
    try {
      const res = await fetch(window.__TIMELINE_NEW_URL__, {
        method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body),
      });
      const data = await res.json();
      if (data.ok) { window.location.href = data.url; return; }
      if (data.report) {
        showErrors(data.report.errors);
        els.force.hidden = false;
      } else {
        showErrors([data.error || T("timeline.ui.network_error")]);
      }
    } catch (e) {
      showErrors([T("timeline.ui.network_error")]);
    } finally {
      els.create.disabled = false;
    }
  }

  function readFile(file) {
    if (!file) return;
    const reader = new FileReader();
    reader.onload = () => {
      els.json.value = String(reader.result || "");
      els.dropLabel.textContent = file.name;
      resetErrors();
    };
    reader.readAsText(file, "utf-8");
  }

  els.open.addEventListener("click", () => {
    resetErrors();
    dialog.showModal();
    (tab === "text" ? els.title : els.json).focus();
  });
  for (const button of [els.close, els.cancel]) button.addEventListener("click", () => dialog.close());
  els.tabs.addEventListener("click", (ev) => {
    const button = ev.target.closest("[data-tab]");
    if (button) setTab(button.dataset.tab);
  });
  els.tabs.addEventListener("keydown", (ev) => {
    if (ev.key !== "ArrowLeft" && ev.key !== "ArrowRight") return;
    const next = tab === "text" ? "json" : "text";
    setTab(next);
    els.tabs.querySelector(`[data-tab="${next}"]`).focus();
  });
  els.create.addEventListener("click", () => submit(false));
  els.force.addEventListener("click", () => submit(true));
  dialog.addEventListener("keydown", (ev) => {
    if ((ev.ctrlKey || ev.metaKey) && ev.key === "Enter") { ev.preventDefault(); submit(false); }
  });

  // Fichier : clic ou dépôt sur la zone.
  els.drop.addEventListener("click", () => els.file.click());
  els.drop.addEventListener("keydown", (ev) => {
    if (ev.key === "Enter" || ev.key === " ") { ev.preventDefault(); els.file.click(); }
  });
  els.file.addEventListener("change", () => readFile(els.file.files[0]));
  els.drop.addEventListener("dragover", (ev) => { ev.preventDefault(); els.drop.classList.add("drop-zone--over"); });
  for (const type of ["dragleave", "dragend"]) {
    els.drop.addEventListener(type, () => els.drop.classList.remove("drop-zone--over"));
  }
  els.drop.addEventListener("drop", (ev) => {
    ev.preventDefault();
    els.drop.classList.remove("drop-zone--over");
    readFile(ev.dataTransfer.files[0]);
  });
})();
