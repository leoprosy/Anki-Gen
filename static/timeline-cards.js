/* ============================================================
   Ankigen — page frise : onglet Cartes (§10)
   Les cartes sont générées par le serveur depuis la frise
   ENREGISTRÉE : choix des types, deck (figé à la première
   génération, modifiable), aperçu rendu comme l'onglet Cartes de
   la vue de travail, interrupteur par carte, puis export TSV, ZIP
   ou copie des images dans collection.media.
   ============================================================ */
(() => {
  const panel = document.getElementById("tl-panel-cards");
  if (!panel) return;
  const URLS = window.__TIMELINE_URLS__;
  const T = (key, params) => window.T(key, params);
  const $ = (id) => document.getElementById(id);
  const toast = (message, kind, ms) => window.toast && window.toast(message, kind, ms);
  const escapeHtml = (s) => String(s == null ? "" : s).replace(/[&<>"']/g, (c) => (
    { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
  const page = () => window.TimelinePage || { isDirty: () => false, save: async () => true, setTab: () => {} };

  const els = {
    types: $("tl-card-types"), deck: $("tl-cards-deck"), list: $("tl-cards-list"), summary: $("tl-cards-summary"),
    unsaved: $("tl-cards-unsaved"), save: $("tl-cards-save"), tsv: $("tl-cards-tsv"), zip: $("tl-cards-zip"),
    anki: $("tl-cards-anki"), profiles: $("tl-cards-profiles"), open: $("tl-cards-open"),
  };
  let data = null;
  let seq = 0;

  async function request(body) {
    const mine = ++seq;
    els.list.classList.add("is-busy");
    let result = null;
    try {
      const response = await fetch(URLS.cards, {
        method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body || {}),
      });
      result = await response.json();
      if (!response.ok || !result.ok) throw new Error(result.error || "");
    } catch (e) {
      if (mine === seq) {
        els.list.classList.remove("is-busy");
        toast((e && e.message) || T("timeline.ui.network_error"), "err");
      }
      return;
    }
    if (mine !== seq) return;
    els.list.classList.remove("is-busy");
    data = result;
    render();
  }

  function render() {
    els.unsaved.hidden = !page().isDirty();
    for (const box of els.types.querySelectorAll("input[type=checkbox]")) {
      box.checked = data.types.includes(box.value);
      const count = els.types.querySelector(`[data-count="${box.value}"]`);
      if (count) count.textContent = box.checked && data.counts[box.value] ? String(data.counts[box.value]) : "";
    }
    if (document.activeElement !== els.deck) els.deck.value = data.deck || "";
    const disabled = data.cards.length - data.enabled;
    els.summary.textContent = data.has_data
      ? T("timeline.ui.cards_summary", { n: data.enabled, total: data.cards.length })
        + (disabled ? ` · ${T("timeline.ui.cards_disabled", { n: disabled })}` : "")
      : T("timeline.api.empty");
    for (const button of [els.tsv, els.zip, els.anki]) button.disabled = !data.enabled;
    els.list.innerHTML = data.cards.length ? data.cards.map((card, i) => `
      <article class="card-preview tl-card${card.enabled ? "" : " is-off"}" data-id="${escapeHtml(card.id)}">
        <header class="tl-card__head">
          <span class="card-label">${escapeHtml(T(`timeline.ui.card_type_${card.type}`))} · ${i + 1}</span>
          <label class="tl-check tl-card__toggle">
            <input type="checkbox" data-toggle="${escapeHtml(card.id)}"${card.enabled ? " checked" : ""}>
            ${escapeHtml(T("timeline.ui.cards_include"))}
          </label>
        </header>
        <div class="card-side"><span class="card-label">${escapeHtml(T("timeline.ui.cards_front"))}</span><div class="card-body">${card.front}</div></div>
        <div class="card-side"><span class="card-label">${escapeHtml(T("timeline.ui.cards_back"))}</span><div class="card-body">${card.back}</div></div>
      </article>`).join("")
      : `<div class="pane-note empty">${escapeHtml(T(data.has_data ? "timeline.ui.cards_none" : "timeline.api.empty"))}</div>`;
    els.profiles.hidden = true;
  }

  function selectedTypes() {
    return [...els.types.querySelectorAll("input[type=checkbox]:checked")].map((box) => box.value);
  }

  // ── Export : comme les cartes de la vue de travail ──────────
  async function download(url) {
    try {
      const response = await fetch(url);
      if (!response.ok) throw new Error("export");
      const blob = await response.blob();
      const name = (response.headers.get("Content-Disposition") || "")
        .split("filename=").pop().replace(/["';]/g, "") || "cards";
      const href = URL.createObjectURL(blob);
      const link = document.createElement("a");
      link.href = href;
      link.download = name;
      document.body.appendChild(link);
      link.click();
      link.remove();
      URL.revokeObjectURL(href);
      const error = response.headers.get("X-Export-Error");
      const path = response.headers.get("X-Export-Path");
      if (error) toast(decodeURIComponent(error), "err", 5000);
      else if (path) toast(T("timeline.ui.export_done", { path: decodeURIComponent(path) }), "ok", 4000);
    } catch (e) {
      toast(T("timeline.ui.export_failed"), "err");
    }
  }

  function showProfiles() {
    const profiles = (data && data.anki_profiles) || [];
    els.profiles.hidden = false;
    els.profiles.innerHTML = profiles.length
      ? `<div class="muted">${escapeHtml(window.T("js.choose_profile"))}</div>` + profiles.map((p) =>
        `<button type="button" class="profile-btn" data-path="${escapeHtml(p.path)}">${escapeHtml(p.profile)}</button>`).join("")
      : `<div class="muted">${escapeHtml(window.T("js.no_anki_profile"))}</div>`;
  }

  async function copyToAnki(path) {
    els.profiles.innerHTML = `<div class="muted">${escapeHtml(window.T("js.copying"))}</div>`;
    try {
      const response = await fetch(URLS.cardsAnkiMedia, {
        method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ path }),
      });
      const body = await response.json();
      if (!response.ok) throw new Error(body.error || "");
      const res = body.result;
      const bits = [window.T("js.copied_count", { n: res.copied.length })];
      if (res.identical.length) bits.push(window.T("js.already_current", { n: res.identical.length }));
      if (res.conflicts.length) bits.push(window.T("js.conflicts", { n: res.conflicts.length, names: res.conflicts.join(", ") }));
      if (res.missing.length) bits.push(window.T("js.missing_count", { n: res.missing.length }));
      els.profiles.innerHTML = `<div class="${res.conflicts.length || res.missing.length ? "export-status err" : "export-status ok"}">`
        + `${escapeHtml(body.message || bits.join(" · "))}</div>`;
    } catch (e) {
      els.profiles.innerHTML = `<div class="export-status err">${escapeHtml((e && e.message) || T("timeline.ui.network_error"))}</div>`;
    }
  }

  // ── Écouteurs ────────────────────────────────────────────────
  els.types.addEventListener("change", () => request({ types: selectedTypes() }));
  els.deck.addEventListener("change", () => { if (els.deck.value.trim()) request({ deck: els.deck.value }); });
  els.deck.addEventListener("keydown", (ev) => { if (ev.key === "Enter") { ev.preventDefault(); els.deck.blur(); } });
  els.list.addEventListener("change", (ev) => {
    const box = ev.target.closest("[data-toggle]");
    if (!box) return;
    box.closest(".tl-card").classList.toggle("is-off", !box.checked);
    request({ toggle: { id: box.dataset.toggle, enabled: box.checked } });
  });
  els.tsv.addEventListener("click", () => download(URLS.cardsTsv));
  els.zip.addEventListener("click", () => download(URLS.cardsZip));
  els.anki.addEventListener("click", showProfiles);
  els.profiles.addEventListener("click", (ev) => {
    const button = ev.target.closest(".profile-btn");
    if (button) copyToAnki(button.dataset.path);
  });
  els.save.addEventListener("click", async () => { if (await page().save()) request({}); });
  els.open.addEventListener("click", () => page().setTab("cards"));
  document.addEventListener("timeline:tab", (ev) => { if (ev.detail.tab === "cards") request({}); });
  document.addEventListener("timeline:saved", () => { if (!panel.hidden) request({}); });
})();
