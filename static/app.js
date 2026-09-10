(() => {
  const prompts = window.PROMPTS || PROMPTS;
  if (!prompts || !prompts.length) return;

  const els = {
    list: document.getElementById("chunk-list"),
    curId: document.getElementById("cur-id"),
    curDeck: document.getElementById("cur-deck"),
    curPrompt: document.getElementById("cur-prompt"),
    curPreview: document.getElementById("cur-preview"),
    altPanel: document.getElementById("alt-panel"),
    insertBar: document.getElementById("insert-bar"),
    response: document.getElementById("response"),
    responseContainer: document.getElementById("response-container"),
    cardsPreview: document.getElementById("cards-preview"),
    saveBtn: document.getElementById("save-btn"),
    saveNextBtn: document.getElementById("save-next-btn"),
    saveStatus: document.getElementById("save-status"),
    prevBtn: document.getElementById("prev-btn"),
    nextBtn: document.getElementById("next-btn"),
    progressLabel: document.getElementById("progress-label"),
    progressFill: document.getElementById("progress-fill"),
    cardsInfo: document.getElementById("cards-info"),
    chunkView: document.getElementById("chunk-view"),
    viewToggle: document.getElementById("view-toggle"),
    answerToggle: document.getElementById("answer-toggle"),
  };

  const firstPending = prompts.findIndex(p => p.status !== "done");
  let currentIdx = firstPending >= 0 ? firstPending : 0;
  let answerMode = "edit";

  const escapeHtml = (s) => (s || "").replace(/[&<>"]/g, c => (
    { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]
  ));

  // ── Chunk transition (cross-fade) ──────────────────────────
  function transitionChunkView(callback) {
    if (!els.chunkView) { callback(); return; }
    els.chunkView.classList.add("switching");
    setTimeout(() => {
      callback();
      els.chunkView.classList.remove("switching");
    }, 150);
  }

  // ── Panneau texte alternatif ───────────────────────────────
  function renderAltPanel(p) {
    if (!els.altPanel) return;
    const images = p.images || [];
    if (!images.length) { els.altPanel.innerHTML = ""; return; }

    els.altPanel.innerHTML = `
      <h5>Descriptions des images <span class="muted">(envoyées à Claude avec le paragraphe)</span></h5>
      ${images.map(img => `
        <div class="alt-row ${img.alt ? "" : "alt-row--missing"}" data-asset="${escapeHtml(img.id)}">
          <div class="alt-thumb">
            ${img.url ? `<img src="${escapeHtml(img.url)}" alt="">`
                      : `<span class="alt-thumb--missing">✕</span>`}
          </div>
          <div class="alt-fields">
            <label class="alt-tag">${img.n ? `{{IMG:${img.n}}}`
                                          : `image du {{TABLE:${img.in_table}}}`}</label>
            <textarea rows="2" class="alt-input"
              placeholder="Décris cette image pour Claude (ce que montre le graphique, ses axes, sa source…)">${escapeHtml(img.alt || "")}</textarea>
          </div>
          <div class="alt-actions">
            <button type="button" class="btn ghost alt-save">Enregistrer</button>
            <span class="alt-status muted"></span>
          </div>
        </div>`).join("")}
    `;
  }

  function renderInsertBar(p) {
    if (!els.insertBar) return;
    const chips = [];
    (p.images || []).forEach(img => chips.push(`{{IMG:${img.n}}}`));
    (p.tables || []).forEach(t => chips.push(`{{TABLE:${t.n}}}`));
    if (!chips.length) { els.insertBar.innerHTML = ""; els.insertBar.hidden = true; return; }
    els.insertBar.hidden = false;
    els.insertBar.innerHTML =
      `<span class="muted">Insérer :</span>` +
      chips.map(c => `<button type="button" class="chip" data-insert="${escapeHtml(c)}">${escapeHtml(c)}</button>`).join("");
  }

  function render() {
    const p = prompts[currentIdx];
    els.curId.textContent = `#${p.id}`;
    els.curDeck.textContent = p.deck;
    els.curPrompt.textContent = p.prompt;
    els.curPreview.innerHTML = p.preview_html || `<p class="pv-text">${escapeHtml(p.prompt)}</p>`;
    els.response.value = p.response || "";
    renderAltPanel(p);
    renderInsertBar(p);
    updateCardsInfo();
    els.saveStatus.textContent = "";
    els.saveStatus.className = "muted";
    if (answerMode === "cards") refreshCardsPreview();

    for (const li of els.list.querySelectorAll(".chunk-item")) {
      const id = parseInt(li.dataset.id, 10);
      li.classList.toggle("active", id === p.id);
    }

    els.prevBtn.disabled = currentIdx === 0;
    els.nextBtn.disabled = currentIdx === prompts.length - 1;

    const activeLi = els.list.querySelector(".chunk-item.active");
    if (activeLi) activeLi.scrollIntoView({ block: "nearest", inline: "nearest", behavior: "smooth" });
  }

  function navigateTo(idx) {
    if (idx < 0 || idx >= prompts.length || idx === currentIdx) return;
    transitionChunkView(() => {
      currentIdx = idx;
      render();
    });
  }

  function updateProgress() {
    const total = prompts.length;
    const done = prompts.filter(p => p.status === "done").length;
    els.progressLabel.textContent = `${done}/${total}`;
    els.progressFill.style.width = total ? `${(100 * done / total).toFixed(1)}%` : "0%";
  }

  function updateCardsInfo() {
    const text = els.response.value.trim();
    if (!text) {
      els.cardsInfo.textContent = "";
      return;
    }
    const lines = text.split(/\r?\n/).filter(l => l.trim() && !l.startsWith("```") && !l.startsWith("#"));
    const cards = lines.filter(l => l.includes("\t") || l.includes(","));
    const media = (text.match(/\{\{\s*(IMG|IMAGE|TABLE|TABLEAU)\s*[:\-# ]?\s*\d+\s*\}\}/gi) || []).length;
    els.cardsInfo.textContent =
      `${cards.length} carte(s) détectée(s)` + (media ? ` · ${media} média(s) référencé(s)` : "");
  }

  // ── Aperçu des cartes ──────────────────────────────────────
  async function refreshCardsPreview() {
    const p = prompts[currentIdx];
    els.cardsPreview.innerHTML = `<div class="muted">Rendu…</div>`;
    try {
      const r = await fetch(window.__API_PREVIEW_URL__, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ id: p.id, response: els.response.value }),
      });
      const data = await r.json();
      if (!r.ok) throw new Error(data.error || "Erreur");

      if (!data.cards.length) {
        els.cardsPreview.innerHTML = `<div class="muted">Aucune carte à prévisualiser.</div>`;
        return;
      }
      const warn = data.unknown_placeholders.length
        ? `<div class="preview-warn">⚠️ Placeholder(s) sans correspondance, supprimé(s) à l'export : ${data.unknown_placeholders.map(escapeHtml).join(", ")}</div>`
        : "";
      els.cardsPreview.innerHTML = warn + data.cards.map((c, i) => `
        <div class="card-preview">
          <div class="card-side"><span class="card-label">Recto ${i + 1}</span><div class="card-body">${c.question}</div></div>
          <div class="card-side"><span class="card-label">Verso</span><div class="card-body">${c.answer}</div></div>
        </div>`).join("");
    } catch (e) {
      els.cardsPreview.innerHTML = `<div class="err">✗ ${escapeHtml(e.message)}</div>`;
    }
  }

  function setAnswerMode(mode) {
    answerMode = mode;
    const showCards = mode === "cards";
    els.responseContainer.hidden = showCards;
    els.cardsPreview.hidden = !showCards;
    els.answerToggle.querySelectorAll("button").forEach(b =>
      b.classList.toggle("active", b.dataset.answer === mode));
    if (showCards) refreshCardsPreview();
  }

  // ── Sauvegarde ─────────────────────────────────────────────
  async function save({ advance = false } = {}) {
    const p = prompts[currentIdx];
    const response = els.response.value;
    els.saveStatus.textContent = "…";
    els.saveStatus.className = "muted";

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

      const li = els.list.querySelector(`.chunk-item[data-id="${p.id}"]`);
      if (li) li.dataset.status = p.status;

      updateProgress();

      // Save feedback with pulse animation
      els.saveStatus.textContent = `✓ enregistré (${data.cards_detected} cartes)`;
      els.saveStatus.className = "ok";
      els.saveStatus.style.animation = "none";
      // Force reflow to restart animation
      void els.saveStatus.offsetWidth;
      els.saveStatus.style.animation = "";

      if (advance && currentIdx < prompts.length - 1) {
        navigateTo(currentIdx + 1);
      }
    } catch (e) {
      els.saveStatus.textContent = `✗ ${e.message}`;
      els.saveStatus.className = "err";
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
      (data.prompts || []).forEach(updated => {
        const idx = prompts.findIndex(p => p.id === updated.id);
        if (idx >= 0) {
          updated.response = prompts[idx].response;
          updated.status = prompts[idx].status;
          prompts[idx] = updated;
        }
      });
      row.classList.toggle("alt-row--missing", !data.alt);
      status.textContent = `✓ ${data.updated.length} chunk(s) mis à jour`;
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

  // ── Export ─────────────────────────────────────────────────
  const exportMenu = document.getElementById("export-menu");
  const exportReport = document.getElementById("export-report");
  const exportProfiles = document.getElementById("export-profiles");
  const exportStatus = document.getElementById("export-status");
  let lastReport = null;

  async function loadReport() {
    exportReport.textContent = "Calcul du rapport…";
    try {
      const r = await fetch(window.__API_REPORT_URL__);
      const data = await r.json();
      lastReport = data;
      const bits = [
        `${data.cards} carte(s)`,
        `${data.media.length} image(s) utilisée(s)`,
      ];
      if (data.unused_assets.length) bits.push(`${data.unused_assets.length} image(s) non exploitée(s)`);
      if (data.unknown_placeholders.length) bits.push(`${data.unknown_placeholders.length} placeholder(s) orphelin(s)`);
      exportReport.innerHTML = bits.map(escapeHtml).join(" · ");
    } catch (e) {
      exportReport.textContent = "Rapport indisponible.";
    }
  }

  function renderProfiles() {
    const profiles = (lastReport && lastReport.anki_profiles) || [];
    if (!profiles.length) {
      exportProfiles.hidden = false;
      exportProfiles.innerHTML =
        `<div class="muted">Aucun profil Anki détecté sur cette machine. Utilise l'export ZIP.</div>`;
      return;
    }
    exportProfiles.hidden = false;
    exportProfiles.innerHTML =
      `<div class="muted">Anki doit être fermé. Choisis le profil :</div>` +
      profiles.map(p => `
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
    document.getElementById("copy-media-btn").addEventListener("click", renderProfiles);
    exportProfiles.addEventListener("click", (ev) => {
      const btn = ev.target.closest(".profile-btn");
      if (btn) copyMedia(btn.dataset.path);
    });
    document.addEventListener("click", (ev) => {
      if (exportMenu.open && !exportMenu.contains(ev.target)) exportMenu.open = false;
    });
  }

  // ── Event listeners ────────────────────────────────────────
  els.list.addEventListener("click", (ev) => {
    const btn = ev.target.closest(".chunk-btn");
    if (!btn) return;
    const li = btn.closest(".chunk-item");
    const id = parseInt(li.dataset.id, 10);
    const idx = prompts.findIndex(p => p.id === id);
    if (idx >= 0) navigateTo(idx);
  });

  els.prevBtn.addEventListener("click", () => navigateTo(currentIdx - 1));
  els.nextBtn.addEventListener("click", () => navigateTo(currentIdx + 1));

  els.saveBtn.addEventListener("click", () => save({ advance: false }));
  els.saveNextBtn.addEventListener("click", () => save({ advance: true }));
  els.response.addEventListener("input", updateCardsInfo);

  els.viewToggle.addEventListener("click", (ev) => {
    const btn = ev.target.closest("button[data-view]");
    if (!btn) return;
    const view = btn.dataset.view;
    els.viewToggle.querySelectorAll("button").forEach(b =>
      b.classList.toggle("active", b === btn));
    els.curPreview.hidden = view !== "preview";
    els.curPrompt.hidden = view !== "text";
  });

  els.answerToggle.addEventListener("click", (ev) => {
    const btn = ev.target.closest("button[data-answer]");
    if (btn) setAnswerMode(btn.dataset.answer);
  });

  els.insertBar.addEventListener("click", (ev) => {
    const btn = ev.target.closest(".chip");
    if (!btn) return;
    const ta = els.response;
    const start = ta.selectionStart, end = ta.selectionEnd;
    ta.value = ta.value.slice(0, start) + btn.dataset.insert + ta.value.slice(end);
    ta.selectionStart = ta.selectionEnd = start + btn.dataset.insert.length;
    ta.focus();
    updateCardsInfo();
  });

  els.altPanel.addEventListener("click", (ev) => {
    const btn = ev.target.closest(".alt-save");
    if (btn) saveAlt(btn.closest(".alt-row"));
  });

  // Agrandissement d'une image de l'aperçu
  els.curPreview.addEventListener("click", (ev) => {
    const img = ev.target.closest(".pv-image img");
    if (!img) return;
    const box = document.createElement("div");
    box.className = "lightbox";
    box.innerHTML = `<img src="${img.getAttribute("src")}" alt="">`;
    box.addEventListener("click", () => box.remove());
    document.addEventListener("keydown", function esc(e) {
      if (e.key === "Escape") { box.remove(); document.removeEventListener("keydown", esc); }
    });
    document.body.appendChild(box);
  });

  els.altPanel.addEventListener("keydown", (ev) => {
    if ((ev.ctrlKey || ev.metaKey) && ev.key === "Enter" && ev.target.classList.contains("alt-input")) {
      ev.preventDefault();
      saveAlt(ev.target.closest(".alt-row"));
    }
  });

  // Ctrl+Enter = Save & next
  els.response.addEventListener("keydown", (ev) => {
    if ((ev.ctrlKey || ev.metaKey) && ev.key === "Enter") {
      ev.preventDefault();
      save({ advance: true });
    }
  });

  // Paste button
  const pasteBtn = document.getElementById('paste-btn');
  if (pasteBtn) {
    pasteBtn.addEventListener('click', async () => {
      try {
        const text = await navigator.clipboard.readText();
        if (text) {
          els.response.value = text;
          updateCardsInfo();
        }
      } catch (err) {
        console.error('Failed to read clipboard: ', err);
      }
    });
  }

  // Response container drag and drop
  const responseContainer = els.responseContainer;
  if (responseContainer) {
    responseContainer.addEventListener('dragover', (e) => {
      e.preventDefault();
      responseContainer.classList.add('drag-over');
    });

    ['dragleave', 'dragend'].forEach(type => {
      responseContainer.addEventListener(type, () => {
        responseContainer.classList.remove('drag-over');
      });
    });

    responseContainer.addEventListener('drop', (e) => {
      e.preventDefault();
      responseContainer.classList.remove('drag-over');
      if (e.dataTransfer.files && e.dataTransfer.files.length > 0) {
        const file = e.dataTransfer.files[0];
        const reader = new FileReader();
        reader.onload = (event) => {
          els.response.value = event.target.result;
          updateCardsInfo();
        };
        reader.readAsText(file);
      }
    });
  }

  // Copy buttons
  document.querySelectorAll(".copy-btn").forEach(btn => {
    btn.addEventListener("click", async (ev) => {
      ev.stopPropagation();
      const sel = btn.dataset.copyTarget;
      const target = sel ? document.querySelector(sel) : null;
      if (!target) return;
      const text = target.textContent || target.value || "";
      try {
        await navigator.clipboard.writeText(text);
        const orig = btn.textContent;
        btn.textContent = "✓ Copié";
        btn.classList.add("copied");
        setTimeout(() => { btn.textContent = orig; btn.classList.remove("copied"); }, 1200);
      } catch {
        btn.textContent = "✗ Échec";
      }
    });
  });

  render();
  updateProgress();
})();
