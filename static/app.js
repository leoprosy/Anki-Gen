/* ============================================================
   Anki-Gen — logique de la vue « travail »
   Principe : toutes les actions principales (copier / coller /
   aperçu / enregistrer / naviguer) vivent dans le dock, qui reste
   visible quelle que soit la taille de la fenêtre.
   ============================================================ */
(() => {
  const prompts = window.PROMPTS || (typeof PROMPTS !== "undefined" ? PROMPTS : null);
  if (!prompts || !prompts.length) return;

  const $ = (id) => document.getElementById(id);

  const els = {
    list: $("chunk-list"),
    rail: $("rail"),
    railToggle: $("rail-toggle"),
    railClose: $("rail-close"),
    railScrim: $("rail-scrim"),
    tabbar: $("tabbar"),
    tabFlag: $("tab-flag"),
    panesGrid: $("panes-grid"),
    curId: $("cur-id"),
    curDeck: $("cur-deck"),
    curPrompt: $("cur-prompt"),
    curPreview: $("cur-preview"),
    altPanel: $("alt-panel"),
    insertBar: $("insert-bar"),
    response: $("response"),
    responseContainer: $("response-container"),
    cardsPreview: $("cards-preview"),
    cardsInfo: $("cards-info"),
    viewToggle: $("view-toggle"),
    answerToggle: $("answer-toggle"),
    progressLabel: $("progress-label"),
    progressFill: $("progress-fill"),
    counter: $("dock-counter"),
    prevBtn: $("prev-btn"),
    nextBtn: $("next-btn"),
    copyBtn: $("copy-btn"),
    pasteBtn: $("paste-btn"),
    previewBtn: $("preview-btn"),
    saveBtn: $("save-btn"),
    saveNextBtn: $("save-next-btn"),
  };

  const mqDrawer = window.matchMedia("(max-width: 1180px)");
  const mqTabs = window.matchMedia("(max-width: 900px)");

  const firstPending = prompts.findIndex((p) => p.status !== "done");
  let currentIdx = firstPending >= 0 ? firstPending : 0;
  let answerMode = "edit";       // edit | cards
  let dirty = false;             // réponse modifiée non enregistrée

  const escapeHtml = (s) =>
    (s || "").replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));

  const toast = (msg, kind, ms) => window.toast && window.toast(msg, kind, ms);

  // ── Tiroir (rail) ──────────────────────────────────────────
  function setRail(open) {
    document.body.classList.toggle("rail-open", open);
    if (els.railToggle) els.railToggle.setAttribute("aria-expanded", String(open));
  }
  els.railToggle && els.railToggle.addEventListener("click", () =>
    setRail(!document.body.classList.contains("rail-open")));
  els.railClose && els.railClose.addEventListener("click", () => setRail(false));
  els.railScrim && els.railScrim.addEventListener("click", () => setRail(false));

  // ── Onglets (petites fenêtres) ─────────────────────────────
  function setTab(tab) {
    els.panesGrid.dataset.active = tab;
    els.tabbar.querySelectorAll("button").forEach((b) => {
      const on = b.dataset.tab === tab;
      b.classList.toggle("active", on);
      b.setAttribute("aria-selected", String(on));
    });
  }
  els.tabbar.addEventListener("click", (ev) => {
    const btn = ev.target.closest("button[data-tab]");
    if (btn) setTab(btn.dataset.tab);
  });
  /** Amène le panneau demandé sous les yeux, même en mode onglets. */
  function focusPane(pane) {
    if (mqTabs.matches) setTab(pane);
  }

  // ── Panneau des textes alternatifs ─────────────────────────
  function renderAltPanel(p) {
    const images = p.images || [];
    if (!images.length) { els.altPanel.innerHTML = ""; return; }

    els.altPanel.innerHTML = `
      <h5>Descriptions des images <span class="muted">(envoyées à Claude avec le paragraphe)</span></h5>
      ${images.map((img) => `
        <div class="alt-row ${img.alt ? "" : "alt-row--missing"}" data-asset="${escapeHtml(img.id)}">
          <div class="alt-thumb">
            ${img.url ? `<img src="${escapeHtml(img.url)}" alt="">`
                      : `<span class="alt-thumb--missing">✕</span>`}
          </div>
          <div class="alt-fields">
            <label class="alt-tag">${img.n ? `{{IMG:${img.n}}}` : `image du {{TABLE:${img.in_table}}}`}</label>
            <textarea rows="2" class="alt-input"
              placeholder="Décris cette image pour Claude (ce que montre le graphique, ses axes, sa source…)">${escapeHtml(img.alt || "")}</textarea>
          </div>
          <div class="alt-actions">
            <span class="alt-status muted"></span>
            <button type="button" class="btn sm alt-save">Enregistrer</button>
          </div>
        </div>`).join("")}
    `;
  }

  function renderInsertBar(p) {
    const chips = [];
    (p.images || []).forEach((img) => { if (img.n) chips.push(`{{IMG:${img.n}}}`); });
    (p.tables || []).forEach((t) => chips.push(`{{TABLE:${t.n}}}`));
    if (!chips.length) { els.insertBar.innerHTML = ""; els.insertBar.hidden = true; return; }
    els.insertBar.hidden = false;
    els.insertBar.innerHTML =
      `<span class="muted">Insérer :</span>` +
      chips.map((c) => `<button type="button" class="chip" data-insert="${escapeHtml(c)}">${escapeHtml(c)}</button>`).join("");
  }

  function setDirty(on) {
    dirty = on;
    if (els.tabFlag) els.tabFlag.hidden = !on;
  }

  // ── Rendu du chunk courant ─────────────────────────────────
  function render() {
    const p = prompts[currentIdx];
    els.curId.textContent = `#${p.id}`;
    els.curDeck.textContent = p.deck;
    els.curDeck.title = p.deck;
    els.curPrompt.textContent = p.prompt;
    els.curPreview.innerHTML = p.preview_html || `<p class="pv-text">${escapeHtml(p.prompt)}</p>`;
    els.response.value = p.response || "";
    renderAltPanel(p);
    renderInsertBar(p);
    updateCardsInfo();
    setDirty(false);

    for (const li of els.list.querySelectorAll(".chunk-item")) {
      li.classList.toggle("active", parseInt(li.dataset.id, 10) === p.id);
    }

    els.prevBtn.disabled = currentIdx === 0;
    els.nextBtn.disabled = currentIdx === prompts.length - 1;
    els.counter.textContent = `${currentIdx + 1}/${prompts.length}`;

    const activeLi = els.list.querySelector(".chunk-item.active");
    if (activeLi) activeLi.scrollIntoView({ block: "nearest" });

    els.panesGrid.querySelectorAll(".pane__body").forEach((b) => { b.scrollTop = 0; });
    if (answerMode === "cards") refreshCardsPreview();
  }

  function navigateTo(idx) {
    if (idx < 0 || idx >= prompts.length || idx === currentIdx) return;
    currentIdx = idx;
    render();
  }

  function updateProgress() {
    const total = prompts.length;
    const done = prompts.filter((p) => p.status === "done").length;
    els.progressLabel.textContent = `${done}/${total}`;
    els.progressFill.style.width = total ? `${(100 * done / total).toFixed(1)}%` : "0%";
  }

  function updateCardsInfo() {
    const text = els.response.value.trim();
    if (!text) { els.cardsInfo.textContent = ""; return; }
    const lines = text.split(/\r?\n/).filter((l) => l.trim() && !l.startsWith("```") && !l.startsWith("#"));
    const cards = lines.filter((l) => l.includes("\t") || l.includes(","));
    const media = (text.match(/\{\{\s*(IMG|IMAGE|TABLE|TABLEAU)\s*[:\-# ]?\s*\d+\s*\}\}/gi) || []).length;
    els.cardsInfo.textContent = `${cards.length} carte(s)` + (media ? ` · ${media} média(s)` : "");
  }

  // ── Aperçu des cartes ──────────────────────────────────────
  async function refreshCardsPreview() {
    const p = prompts[currentIdx];
    els.cardsPreview.innerHTML = `<div class="pane-note empty">Rendu…</div>`;
    try {
      const r = await fetch(window.__API_PREVIEW_URL__, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ id: p.id, response: els.response.value }),
      });
      const data = await r.json();
      if (!r.ok) throw new Error(data.error || "Erreur");

      if (!data.cards.length) {
        els.cardsPreview.innerHTML =
          `<div class="pane-note empty">Aucune carte à prévisualiser — colle d'abord la réponse de Claude.</div>`;
        return;
      }
      const warn = data.unknown_placeholders.length
        ? `<div class="pane-note warn">⚠️ Placeholder(s) sans correspondance, supprimé(s) à l'export : ${
            data.unknown_placeholders.map(escapeHtml).join(", ")}</div>`
        : "";
      els.cardsPreview.innerHTML = warn + data.cards.map((c, i) => `
        <div class="card-preview">
          <div class="card-side"><span class="card-label">Recto ${i + 1}</span><div class="card-body">${c.question}</div></div>
          <div class="card-side"><span class="card-label">Verso</span><div class="card-body">${c.answer}</div></div>
        </div>`).join("");
    } catch (e) {
      els.cardsPreview.innerHTML = `<div class="pane-note err">✗ ${escapeHtml(e.message)}</div>`;
    }
  }

  function setAnswerMode(mode) {
    answerMode = mode;
    const showCards = mode === "cards";
    els.responseContainer.hidden = showCards;
    els.cardsPreview.hidden = !showCards;
    els.answerToggle.querySelectorAll("button").forEach((b) =>
      b.classList.toggle("active", b.dataset.answer === mode));
    els.previewBtn.setAttribute("aria-pressed", String(showCards));
    els.previewBtn.classList.toggle("copied", showCards);
    const lbl = els.previewBtn.querySelector(".lbl");
    if (lbl) lbl.textContent = showCards ? "Éditer" : "Aperçu";
    if (showCards) refreshCardsPreview();
  }

  // ── Sauvegarde ─────────────────────────────────────────────
  async function save({ advance = false } = {}) {
    const p = prompts[currentIdx];
    const response = els.response.value;
    els.saveBtn.disabled = els.saveNextBtn.disabled = true;

    try {
      const r = await fetch(window.__API_SAVE_URL__ || "/api/save", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ id: p.id, response }),
      });
      const data = await r.json();
      if (!r.ok) throw new Error(data.error || "Erreur");

      p.response = response;
      p.status = data.status;
      setDirty(false);

      const li = els.list.querySelector(`.chunk-item[data-id="${p.id}"]`);
      if (li) li.dataset.status = p.status;
      updateProgress();
      toast(`✓ Chunk #${p.id} enregistré — ${data.cards_detected} carte(s)`, "ok");

      if (advance) {
        if (currentIdx < prompts.length - 1) {
          navigateTo(currentIdx + 1);
          focusPane("answer");
        } else {
          toast("Dernier chunk : tout est enregistré.", "ok");
        }
      }
    } catch (e) {
      toast(`✗ ${e.message}`, "err", 4000);
    } finally {
      els.saveBtn.disabled = els.saveNextBtn.disabled = false;
    }
  }

  // ── Texte alternatif ───────────────────────────────────────
  async function saveAlt(row) {
    const assetId = row.dataset.asset;
    const input = row.querySelector(".alt-input");
    const status = row.querySelector(".alt-status");
    status.textContent = "…";
    status.className = "alt-status muted";

    try {
      const url = window.__API_ASSET_URL__.replace("__ASSET__", encodeURIComponent(assetId));
      const r = await fetch(url, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ alt: input.value }),
      });
      const data = await r.json();
      if (!r.ok) throw new Error(data.error || "Erreur");

      // Les prompts touchés ont été re-rendus côté serveur : on les remplace
      (data.prompts || []).forEach((updated) => {
        const idx = prompts.findIndex((p) => p.id === updated.id);
        if (idx >= 0) {
          updated.response = prompts[idx].response;
          updated.status = prompts[idx].status;
          prompts[idx] = updated;
        }
      });
      row.classList.toggle("alt-row--missing", !data.alt);
      status.textContent = `✓ ${data.updated.length} chunk(s)`;
      status.className = "alt-status ok";

      const p = prompts[currentIdx];
      els.curPrompt.textContent = p.prompt;
      els.curPreview.innerHTML = p.preview_html || "";
      setTimeout(() => { status.textContent = ""; }, 2500);
    } catch (e) {
      status.textContent = `✗ ${e.message}`;
      status.className = "alt-status err";
    }
  }

  // ── Presse-papier ──────────────────────────────────────────
  /**
   * Copie `text`, avec deux replis si l'API presse-papier est refusée :
   * execCommand, puis sélection du texte à l'écran pour un Ctrl+C manuel.
   */
  async function copyText(text, okMsg, selectEl) {
    try {
      await navigator.clipboard.writeText(text);
      toast(okMsg, "ok", 1600);
      return true;
    } catch { /* on tente les replis */ }

    const ta = document.createElement("textarea");
    ta.value = text;
    ta.style.cssText = "position:fixed;top:0;left:0;opacity:0";
    document.body.appendChild(ta);
    ta.select();
    let ok = false;
    try { ok = document.execCommand("copy"); } catch { ok = false; }
    ta.remove();
    if (ok) { toast(okMsg, "ok", 1600); return true; }

    if (selectEl) {
      selectEl.hidden = false;
      const range = document.createRange();
      range.selectNodeContents(selectEl);
      const sel = window.getSelection();
      sel.removeAllRanges();
      sel.addRange(range);
      selectEl.scrollIntoView({ block: "nearest" });
      toast("Texte sélectionné — appuie sur Ctrl+C", "err", 4000);
    } else {
      toast("✗ Copie impossible", "err", 2400);
    }
    return false;
  }

  async function pasteIntoResponse() {
    focusPane("answer");
    if (answerMode === "cards") setAnswerMode("edit");
    try {
      const text = await navigator.clipboard.readText();
      if (!text) { toast("Presse-papier vide", "err", 1800); return; }
      els.response.value = text;
      updateCardsInfo();
      setDirty(true);
      toast("✓ Réponse collée", "ok", 1400);
    } catch {
      els.response.focus();
      toast("Autorise le presse-papier, ou colle avec Ctrl+V", "err", 3200);
    }
  }

  // ── Export ─────────────────────────────────────────────────
  const exportMenu = $("export-menu");
  const exportReport = $("export-report");
  const exportProfiles = $("export-profiles");
  const exportStatus = $("export-status");
  let lastReport = null;

  async function loadReport() {
    exportReport.textContent = "Calcul du rapport…";
    try {
      const r = await fetch(window.__API_REPORT_URL__);
      const data = await r.json();
      lastReport = data;
      const bits = [`${data.cards} carte(s)`, `${data.media.length} image(s) utilisée(s)`];
      if (data.unused_assets.length) bits.push(`${data.unused_assets.length} image(s) non exploitée(s)`);
      if (data.unknown_placeholders.length) bits.push(`${data.unknown_placeholders.length} placeholder(s) orphelin(s)`);
      exportReport.textContent = bits.join(" · ");
    } catch {
      exportReport.textContent = "Rapport indisponible.";
    }
  }

  function renderProfiles() {
    const profiles = (lastReport && lastReport.anki_profiles) || [];
    exportProfiles.hidden = false;
    if (!profiles.length) {
      exportProfiles.innerHTML =
        `<div class="muted">Aucun profil Anki détecté sur cette machine. Utilise l'export ZIP.</div>`;
      return;
    }
    exportProfiles.innerHTML =
      `<div class="muted">Anki doit être fermé. Choisis le profil :</div>` +
      profiles.map((p) => `
        <button type="button" class="profile-btn" data-path="${escapeHtml(p.path)}">
          ${escapeHtml(p.profile)} <span class="muted">(${p.files} fichiers)</span>
        </button>`).join("");
  }

  async function copyMedia(path) {
    exportStatus.textContent = "Copie en cours…";
    exportStatus.className = "export-status muted";
    try {
      const r = await fetch(window.__API_ANKI_MEDIA_URL__, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ path }),
      });
      const data = await r.json();
      if (!r.ok) throw new Error(data.error || "Erreur");
      const res = data.result;
      const bits = [`${res.copied.length} copiée(s)`];
      if (res.identical.length) bits.push(`${res.identical.length} déjà à jour`);
      if (res.conflicts.length) bits.push(`⚠️ ${res.conflicts.length} conflit(s) : ${res.conflicts.join(", ")}`);
      if (res.missing.length) bits.push(`⚠️ ${res.missing.length} introuvable(s)`);
      exportStatus.textContent = bits.join(" · ");
      exportStatus.className = res.conflicts.length || res.missing.length
        ? "export-status err" : "export-status ok";
    } catch (e) {
      exportStatus.textContent = `✗ ${e.message}`;
      exportStatus.className = "export-status err";
    }
  }

  if (exportMenu) {
    exportMenu.addEventListener("toggle", () => {
      if (exportMenu.open) loadReport();
      else { exportProfiles.hidden = true; exportStatus.textContent = ""; }
    });
    $("copy-media-btn").addEventListener("click", renderProfiles);
    $("copy-system-btn").addEventListener("click", () =>
      copyText(window.__SYSTEM_PROMPT__ || "", "✓ Prompt système copié"));
    exportProfiles.addEventListener("click", (ev) => {
      const btn = ev.target.closest(".profile-btn");
      if (btn) copyMedia(btn.dataset.path);
    });
    document.addEventListener("click", (ev) => {
      if (exportMenu.open && !exportMenu.contains(ev.target)) exportMenu.open = false;
    });
  }

  // ── Écouteurs ──────────────────────────────────────────────
  els.list.addEventListener("click", (ev) => {
    const btn = ev.target.closest(".chunk-btn");
    if (!btn) return;
    const id = parseInt(btn.closest(".chunk-item").dataset.id, 10);
    const idx = prompts.findIndex((p) => p.id === id);
    if (idx >= 0) {
      navigateTo(idx);
      if (mqDrawer.matches) setRail(false);
    }
  });

  els.prevBtn.addEventListener("click", () => navigateTo(currentIdx - 1));
  els.nextBtn.addEventListener("click", () => navigateTo(currentIdx + 1));
  els.saveBtn.addEventListener("click", () => save({ advance: false }));
  els.saveNextBtn.addEventListener("click", () => save({ advance: true }));
  els.pasteBtn.addEventListener("click", pasteIntoResponse);
  els.previewBtn.addEventListener("click", () => {
    focusPane("answer");
    setAnswerMode(answerMode === "cards" ? "edit" : "cards");
  });
  els.copyBtn.addEventListener("click", async () => {
    focusPane("source");
    const ok = await copyText(prompts[currentIdx].prompt, "✓ Paragraphe copié", els.curPrompt);
    if (ok) {
      els.copyBtn.classList.add("copied");
      setTimeout(() => els.copyBtn.classList.remove("copied"), 1200);
    } else {
      // La sélection manuelle exige la vue « Texte »
      els.viewToggle.querySelector('[data-view="text"]').click();
    }
  });

  els.response.addEventListener("input", () => { updateCardsInfo(); setDirty(true); });

  els.viewToggle.addEventListener("click", (ev) => {
    const btn = ev.target.closest("button[data-view]");
    if (!btn) return;
    els.viewToggle.querySelectorAll("button").forEach((b) => b.classList.toggle("active", b === btn));
    els.curPreview.hidden = btn.dataset.view !== "preview";
    els.curPrompt.hidden = btn.dataset.view !== "text";
  });

  els.answerToggle.addEventListener("click", (ev) => {
    const btn = ev.target.closest("button[data-answer]");
    if (btn) setAnswerMode(btn.dataset.answer);
  });

  els.insertBar.addEventListener("click", (ev) => {
    const btn = ev.target.closest(".chip");
    if (!btn) return;
    if (answerMode === "cards") setAnswerMode("edit");
    const ta = els.response;
    const start = ta.selectionStart, end = ta.selectionEnd;
    ta.value = ta.value.slice(0, start) + btn.dataset.insert + ta.value.slice(end);
    ta.selectionStart = ta.selectionEnd = start + btn.dataset.insert.length;
    ta.focus();
    updateCardsInfo();
    setDirty(true);
  });

  els.altPanel.addEventListener("click", (ev) => {
    const btn = ev.target.closest(".alt-save");
    if (btn) saveAlt(btn.closest(".alt-row"));
  });
  els.altPanel.addEventListener("keydown", (ev) => {
    if ((ev.ctrlKey || ev.metaKey) && ev.key === "Enter" && ev.target.classList.contains("alt-input")) {
      ev.preventDefault();
      saveAlt(ev.target.closest(".alt-row"));
    }
  });

  // Agrandissement d'une image de l'aperçu
  els.curPreview.addEventListener("click", (ev) => {
    const img = ev.target.closest(".pv-image img");
    if (!img) return;
    const box = document.createElement("div");
    box.className = "lightbox";
    box.innerHTML = `<img src="${img.getAttribute("src")}" alt="">`;
    const close = () => { box.remove(); document.removeEventListener("keydown", onKey); };
    const onKey = (e) => { if (e.key === "Escape") close(); };
    box.addEventListener("click", close);
    document.addEventListener("keydown", onKey);
    document.body.appendChild(box);
  });

  // Dépôt d'un fichier TSV/TXT sur la zone de réponse
  const rc = els.responseContainer;
  rc.addEventListener("dragover", (e) => { e.preventDefault(); rc.classList.add("drag-over"); });
  ["dragleave", "dragend"].forEach((t) =>
    rc.addEventListener(t, () => rc.classList.remove("drag-over")));
  rc.addEventListener("drop", (e) => {
    e.preventDefault();
    rc.classList.remove("drag-over");
    const file = e.dataTransfer.files && e.dataTransfer.files[0];
    if (!file) return;
    const reader = new FileReader();
    reader.onload = (ev) => {
      els.response.value = ev.target.result;
      updateCardsInfo();
      setDirty(true);
      toast(`✓ ${file.name} chargé`, "ok", 1600);
    };
    reader.readAsText(file);
  });

  // ── Raccourcis clavier ─────────────────────────────────────
  document.addEventListener("keydown", (ev) => {
    const mod = ev.ctrlKey || ev.metaKey;

    if (ev.key === "Escape" && document.body.classList.contains("rail-open")) {
      setRail(false);
      return;
    }
    if (mod && ev.key === "Enter") { ev.preventDefault(); save({ advance: true }); return; }
    if (mod && !ev.shiftKey && ev.key.toLowerCase() === "s") { ev.preventDefault(); save(); return; }
    if (mod && ev.shiftKey && ev.key.toLowerCase() === "c") {
      ev.preventDefault(); els.copyBtn.click(); return;
    }
    if (mod && ev.shiftKey && ev.key.toLowerCase() === "v") { ev.preventDefault(); pasteIntoResponse(); return; }
    if (mod && ev.shiftKey && ev.key.toLowerCase() === "p") { ev.preventDefault(); els.previewBtn.click(); return; }
    if (ev.altKey && ev.key === "ArrowLeft") { ev.preventDefault(); navigateTo(currentIdx - 1); return; }
    if (ev.altKey && ev.key === "ArrowRight") { ev.preventDefault(); navigateTo(currentIdx + 1); return; }
  });

  window.addEventListener("beforeunload", (e) => {
    if (!dirty) return;
    e.preventDefault();
    e.returnValue = "";
  });

  // Repasse en vue double quand la fenêtre s'élargit
  mqTabs.addEventListener("change", (e) => { if (!e.matches) setTab("source"); });
  mqDrawer.addEventListener("change", (e) => { if (!e.matches) setRail(false); });

  render();
  updateProgress();
  if (window.__MISSING_ALT__) {
    toast(`${window.__MISSING_ALT__} image(s) sans description`, null, 3600);
  }
})();
