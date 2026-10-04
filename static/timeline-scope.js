/* ============================================================
   Ankigen — vue de travail : « Frise », choix de la portée
   Ce paragraphe, ce chapitre (un ancêtre du chunk courant, déduit
   du deck) ou tout le cours. Le sélecteur montre la taille du texte
   et une estimation de tokens, et propose « paragraphe par
   paragraphe » au-delà du seuil de 25 000 caractères (D1).
   ============================================================ */
(() => {
  const dialog = document.getElementById("tl-scope");
  const CONFIG = window.__TIMELINE_SCOPE__;
  if (!dialog || !CONFIG) return;
  const $ = (id) => document.getElementById(id);
  const T = (key, params) => window.T(key, params);
  const escapeHtml = (s) => String(s == null ? "" : s).replace(/[&<>"']/g, (c) => (
    { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
  const number = (n) => Number(n || 0).toLocaleString(document.documentElement.lang || undefined);

  const els = {
    open: $("tl-scope-open"), close: $("tl-scope-close"), cancel: $("tl-scope-cancel"),
    create: $("tl-scope-create"), choices: $("tl-scope-choices"), level: $("tl-scope-level"),
    chapterRow: $("tl-scope-chapter-row"), strategy: $("tl-scope-strategy"), mode: $("tl-scope-mode"),
    hint: $("tl-scope-hint"), name: $("tl-scope-name"), lang: $("tl-scope-lang"),
    existing: $("tl-scope-existing"), errors: $("tl-scope-errors"),
  };
  let data = null;
  let strategy = "single";
  let strategyTouched = false;
  let mode = "strict";
  let titleTouched = false;
  let langTouched = false;

  function currentChunkId() {
    const active = document.querySelector(".chunk-item.active");
    return active ? active.dataset.id : "";
  }

  function kind() {
    const checked = els.choices.querySelector('input[name="tl-scope"]:checked');
    return checked ? checked.value : null;
  }

  /** Le résumé de la portée choisie : { chunk_ids, chars, tokens, strategy, title, … }. */
  function selected() {
    if (!data) return null;
    if (kind() === "chapter") return data.chapters[Number(els.level.value)] || null;
    return data[kind()] || null;
  }

  function sizeText(summary) {
    if (!summary) return T("timeline.ui.scope_nothing");
    return T("timeline.ui.scope_size", { chunks: summary.chunks, chars: number(summary.chars), tokens: number(summary.tokens) });
  }

  function seg(container, attr, value) {
    for (const button of container.querySelectorAll(`[data-${attr}]`)) {
      const on = button.dataset[attr] === value;
      button.classList.toggle("active", on);
      button.setAttribute("aria-checked", String(on));
    }
  }

  function update() {
    const summary = selected();
    dialog.querySelector('[data-scope-size="chapter"]').textContent =
      data && data.chapters.length ? sizeText(data.chapters[Number(els.level.value)]) : "";
    if (!strategyTouched && summary) strategy = summary.strategy;
    // Un seul paragraphe n'a rien à fusionner.
    const single = !summary || summary.chunks <= 1;
    if (single) strategy = "single";
    els.strategy.querySelector('[data-strategy="per_chunk"]').disabled = single;
    seg(els.strategy, "strategy", strategy);
    seg(els.mode, "mode", mode);
    let hint = "";
    if (summary && strategy === "per_chunk") {
      hint = T("timeline.ui.strategy_per_chunk_help", { n: summary.chunks });
    } else if (summary && summary.chars > data.threshold) {
      hint = T("timeline.ui.strategy_single_warning", { max: number(data.threshold) });
    }
    els.hint.textContent = hint;
    els.hint.classList.toggle("is-warning", !!summary && strategy === "single" && summary.chars > data.threshold);
    if (!titleTouched) els.name.value = summary ? summary.title : "";
    // La langue du contenu règle le prompt et le format des dates : celle du texte, pas de l'interface.
    if (!langTouched && summary && summary.lang && els.lang.querySelector(`option[value="${summary.lang}"]`)) {
      els.lang.value = summary.lang;
    }
    els.create.disabled = !summary;
  }

  function fill() {
    for (const k of ["chunk", "project"]) {
      dialog.querySelector(`[data-scope-size="${k}"]`).textContent = sizeText(data[k]);
      dialog.querySelector(`input[value="${k}"]`).disabled = !data[k];
    }
    // Les niveaux de titre, du plus large au plus étroit, décalés selon leur profondeur.
    els.level.innerHTML = data.chapters.map((chapter, i) =>
      `<option value="${i}" title="${escapeHtml(chapter.path)}">${" ".repeat(Math.max(0, chapter.depth - 1))}`
      + `${escapeHtml(chapter.label)}</option>`).join("");
    els.level.value = data.chapters.length ? String(data.chapters.length - 1) : "";
    els.chapterRow.hidden = !data.chapters.length;
    dialog.querySelector('input[value="chapter"]').disabled = !data.chapters.length;
    const preferred = data.chapters.length ? "chapter" : data.chunk ? "chunk" : "project";
    dialog.querySelector(`input[value="${preferred}"]`).checked = true;
    const existing = data.timelines || [];
    els.existing.hidden = !existing.length;
    els.existing.innerHTML = existing.length
      ? `<span class="muted">${escapeHtml(T("timeline.ui.scope_existing"))}</span> `
        + existing.map((t) => `<a href="/timeline/${encodeURIComponent(t.id)}?chunk_id=${encodeURIComponent(currentChunkId())}">${escapeHtml(t.title)}</a>`).join(", ")
      : "";
    update();
  }

  async function open() {
    const menu = els.open.closest("details");
    if (menu) menu.open = false;
    data = null;
    strategyTouched = false;
    titleTouched = false;
    langTouched = false;
    mode = "strict";
    els.errors.innerHTML = "";
    els.create.disabled = true;
    for (const small of dialog.querySelectorAll("[data-scope-size]")) small.textContent = "…";
    dialog.showModal();
    try {
      const params = new URLSearchParams({ chunk_id: currentChunkId() });
      const response = await fetch(`${CONFIG.scopes}?${params}`);
      data = await response.json();
      if (!response.ok || !data.ok) throw new Error(data.error || "");
    } catch (e) {
      data = null;
      els.errors.innerHTML = `<li>${escapeHtml((e && e.message) || T("timeline.ui.network_error"))}</li>`;
      return;
    }
    fill();
  }

  async function create() {
    const summary = selected();
    if (!summary) return;
    const scope = { kind: kind(), project_id: CONFIG.projectId };
    if (scope.kind === "chapter") scope.deck_path = summary.deck_path;
    if (scope.kind === "chunk") scope.chunk_ids = summary.chunk_ids;
    els.create.disabled = true;
    els.errors.innerHTML = "";
    try {
      const response = await fetch(CONFIG.create, {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ scope, title: els.name.value, lang: els.lang.value, mode, strategy }),
      });
      const body = await response.json();
      if (body.ok) {
        const url = new URL(body.url, window.location.origin);
        const chunk = currentChunkId();
        if (chunk !== "") url.searchParams.set("chunk_id", chunk);
        window.location.href = url.href;
        return;
      }
      els.errors.innerHTML = `<li>${escapeHtml(body.error || T("timeline.ui.network_error"))}</li>`;
    } catch (e) {
      els.errors.innerHTML = `<li>${escapeHtml(T("timeline.ui.network_error"))}</li>`;
    }
    els.create.disabled = false;
  }

  els.open.addEventListener("click", open);
  els.close.addEventListener("click", () => dialog.close());
  els.cancel.addEventListener("click", () => dialog.close());
  els.create.addEventListener("click", create);
  els.choices.addEventListener("change", (ev) => {
    if (ev.target === els.level) dialog.querySelector('input[value="chapter"]').checked = true;
    update();
  });
  els.level.addEventListener("focus", () => {
    dialog.querySelector('input[value="chapter"]').checked = true;
    update();
  });
  els.strategy.addEventListener("click", (ev) => {
    const button = ev.target.closest("[data-strategy]");
    if (!button || button.disabled) return;
    strategy = button.dataset.strategy;
    strategyTouched = true;
    update();
  });
  els.mode.addEventListener("click", (ev) => {
    const button = ev.target.closest("[data-mode]");
    if (!button) return;
    mode = button.dataset.mode;
    update();
  });
  els.name.addEventListener("input", () => { titleTouched = true; });
  els.lang.addEventListener("change", () => { langTouched = true; });
  dialog.addEventListener("click", (ev) => { if (ev.target === dialog) dialog.close(); });
})();
