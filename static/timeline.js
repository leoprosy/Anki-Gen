/* ============================================================
   Ankigen — page frise chronologique
   Le document édité vit ici (state.doc). Chaque modification
   redessine l'aperçu par le serveur (même moteur que l'export),
   250 ms après la dernière frappe. Rien n'est enregistré sans
   « Valider et enregistrer ».
   ============================================================ */
(() => {
  const C = window.TimelineCore;
  const DATA = window.__TIMELINE__;
  const URLS = window.__TIMELINE_URLS__;
  Object.assign(window.__I18N__, window.__TIMELINE_I18N__ || {});
  const T = (key, params) => window.T(key, params);
  const $ = (id) => document.getElementById(id);
  const toast = (message, kind, ms) => window.toast && window.toast(message, kind, ms);
  const clone = (value) => JSON.parse(JSON.stringify(value));
  const escapeHtml = (s) => String(s == null ? "" : s).replace(/[&<>"']/g, (c) => (
    { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));

  const KINDS = ["tracks", "eras", "periods", "events"];
  const SCHEMA = "ankigen.timeline/1";

  function skeleton() {
    return { schema: SCHEMA, title: DATA.title || T("timeline.ui.untitled"), lang: DATA.lang,
             tracks: [], eras: [], periods: [], events: [], links: [] };
  }

  const state = {
    doc: DATA.data ? clone(DATA.data) : skeleton(),
    saved: DATA.data ? C.serialize(DATA.data) : C.serialize(skeleton()),
    jsonDirty: false,
    dates: {},
    notes: {},            // id → numéro de note
    trackStyles: {},      // id → { color, shape }
    report: null,         // dernier rapport de validation du document
    layoutWarnings: [],
    svgSize: null,
    zoom: 1,
    fit: "height",        // "height" à l'ouverture, "width" après « Ajuster », null après un zoom manuel
    theme: "auto",
    density: (DATA.render_options && DATA.render_options.density) || "comfortable",
    editing: null,        // { kind, index } ; index null pour un nouvel élément
    renderSeq: 0,
    quotes: {},           // id → verified | fuzzy | not_found (§6.5)
    extraction: Object.assign({ mode: "strict", strategy: "single", skill: false }, DATA.extraction || {}),
    chunks: DATA.chunks || [],   // paragraphe par paragraphe : { id, heading, title, status, chars, mentions }
    currentChunk: null,
    merge: DATA.merge || null,
    // Après un collage invalide, le prompt montré (et copié) devient le prompt de
    // correction : { chunk: id } en paragraphe par paragraphe, { chunk: null } sinon.
    correction: null,
    prompt: { url: null, text: "" },
    promptSeq: 0,
  };
  const hasSource = !!DATA.has_source_text;

  const els = {
    editor: $("tl-editor"), rail: $("rail"), railToggle: $("rail-toggle"), railClose: $("rail-close"),
    railScrim: $("rail-scrim"), name: $("tl-name"), stateLabel: $("tl-state"),
    tabs: $("tl-tabs"), panelPreview: $("tl-panel-preview"), panelJson: $("tl-panel-json"),
    viewport: $("tl-viewport"), canvas: $("tl-canvas"), empty: $("tl-empty"), tooltip: $("tl-tooltip"),
    json: $("tl-json"), jsonStatus: $("tl-json-status"), jsonErrors: $("tl-json-errors"),
    issues: $("tl-issues"), issuesSummary: $("tl-issues-summary"), issuesList: $("tl-issues-list"),
    drawer: $("tl-drawer"), drawerTitle: $("tl-drawer-title"), form: $("tl-form"),
    tools: $("tl-tools"), zoomValue: $("tl-zoom-value"), add: $("tl-add"),
    panelPrompt: $("tl-panel-prompt"), promptText: $("tl-prompt"), promptSize: $("tl-prompt-size"),
    promptNote: $("tl-prompt-note"), mode: $("tl-mode"), skill: $("tl-skill"), skillCopy: $("tl-skill-copy"),
    chunkNav: $("tl-chunk-nav"), chunkLabel: $("tl-chunk-label"), chunkErrors: $("tl-chunk-errors"),
    correction: $("tl-correction"), correctionSummary: $("tl-correction-summary"),
    correctionWarnings: $("tl-correction-warnings"), correctionBack: $("tl-correction-back"),
    copyPrompt: $("tl-copy-prompt"), copyPromptLabel: $("tl-copy-prompt-label"),
    dockCounter: $("tl-dock-counter"), jsonCorrection: $("tl-json-correction"),
  };

  // ── Requêtes ─────────────────────────────────────────────────
  async function postJson(url, body) {
    const res = await fetch(url, { method: "POST", headers: { "Content-Type": "application/json" },
                                   body: JSON.stringify(body) });
    let data = null;
    try { data = await res.json(); } catch (e) { data = null; }
    return { status: res.status, data };
  }

  // ── État « modifié » ─────────────────────────────────────────
  function isDirty() {
    return state.jsonDirty || C.serialize(state.doc) !== state.saved;
  }

  function updateState() {
    const dirty = isDirty();
    els.stateLabel.textContent = dirty ? T("timeline.ui.unsaved") : "";
    els.name.textContent = state.doc.title || T("timeline.ui.untitled");
    document.title = `${state.doc.title || T("timeline.ui.untitled")} — Ankigen`;
  }

  function hasContent(doc) {
    return !!doc && ((doc.events || []).length > 0 || (doc.periods || []).length > 0);
  }

  /** Toute modification du document passe par ici. */
  function changed({ fromJson = false } = {}) {
    if (!fromJson && !state.jsonDirty) els.json.value = C.serialize(state.doc);
    renderEditor();
    updateState();
    scheduleRender();
  }

  // ── Aperçu ───────────────────────────────────────────────────
  function resolvedTheme() {
    if (state.theme !== "auto") return state.theme;
    return window.matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light";
  }

  async function renderPreview() {
    if (!hasContent(state.doc)) {
      els.canvas.innerHTML = "";
      els.empty.hidden = false;
      els.viewport.hidden = true;
      state.svgSize = null;
      state.report = null;
      state.layoutWarnings = [];
      renderIssues();
      return;
    }
    const seq = ++state.renderSeq;
    els.canvas.classList.add("is-busy");
    let response;
    try {
      response = await postJson(URLS.render, {
        data: state.doc, options: { theme: resolvedTheme(), density: state.density },
      });
    } catch (e) {
      if (seq === state.renderSeq) toast(T("timeline.ui.network_error"), "err");
      return;
    } finally {
      if (seq === state.renderSeq) els.canvas.classList.remove("is-busy");
    }
    if (seq !== state.renderSeq) return;       // une réponse plus récente arrive
    const data = response.data || {};
    if (response.status === 422) {
      state.report = data.report;
      renderIssues();                            // l'ancien dessin reste affiché
      return;
    }
    if (!data.ok) {
      toast(data.error || T("timeline.ui.network_error"), "err");
      return;
    }
    state.report = data.report;
    state.layoutWarnings = data.warnings || [];
    state.dates = data.dates || {};
    state.quotes = data.quotes || {};
    state.notes = {};
    for (const note of data.notes || []) for (const id of note.ref.split("+")) state.notes[id] = note.number;
    state.trackStyles = {};
    for (const track of (data.stats && data.stats.tracks) || []) state.trackStyles[track.id] = track;
    els.empty.hidden = true;
    els.viewport.hidden = false;
    els.canvas.innerHTML = data.svg;
    state.svgSize = { width: data.width, height: data.height };
    applyZoom(state.fit ? fitZoom(state.fit) : state.zoom);
    renderEditor();
    renderIssues();
  }

  const scheduleRender = C.debounce(renderPreview, 250);

  // ── Zoom et déplacement ──────────────────────────────────────
  /**
   * Zoom qui fait tenir la frise dans la vue. À l'ouverture, en hauteur, entre 75 et
   * 100 % : une frise large reste lisible et défile horizontalement.
   * « Ajuster » la fait tenir en largeur, pour la vue d'ensemble.
   */
  // En deçà, le texte de la frise n'est plus lisible : une frise très haute (beaucoup de
  // pistes) s'ouvre à ce zoom et défile aussi verticalement.
  const READABLE_ZOOM = 0.75;

  function fitZoom(mode) {
    if (!state.svgSize) return 1;
    const pad = 26;   // marge intérieure du canevas
    if (mode === "height") {
      return Math.max(READABLE_ZOOM, Math.min(1, (els.viewport.clientHeight - pad) / state.svgSize.height));
    }
    return Math.max(0.1, Math.min(2, (els.viewport.clientWidth - pad) / state.svgSize.width));
  }

  function applyZoom(zoom) {
    const svg = els.canvas.querySelector("svg");
    if (!svg || !state.svgSize) return;
    state.zoom = zoom;
    svg.setAttribute("width", Math.round(state.svgSize.width * zoom));
    svg.setAttribute("height", Math.round(state.svgSize.height * zoom));
    els.zoomValue.textContent = `${Math.round(zoom * 100)} %`;
  }

  function currentZoom() {
    return state.zoom;
  }

  function zoomBy(factor, anchorX, anchorY) {
    state.fit = null;
    const before = currentZoom();
    const after = Math.max(0.1, Math.min(4, before * factor));
    const rect = els.viewport.getBoundingClientRect();
    const ax = anchorX === undefined ? rect.width / 2 : anchorX - rect.left;
    const ay = anchorY === undefined ? rect.height / 2 : anchorY - rect.top;
    const cx = (els.viewport.scrollLeft + ax) / before;
    const cy = (els.viewport.scrollTop + ay) / before;
    applyZoom(after);
    els.viewport.scrollLeft = cx * after - ax;
    els.viewport.scrollTop = cy * after - ay;
  }

  $("tl-zoom-in").addEventListener("click", () => zoomBy(1.25));
  $("tl-zoom-out").addEventListener("click", () => zoomBy(0.8));
  $("tl-zoom-fit").addEventListener("click", () => { state.fit = "width"; applyZoom(fitZoom("width")); });
  els.viewport.addEventListener("wheel", (ev) => {
    if (!ev.ctrlKey) return;
    ev.preventDefault();
    zoomBy(ev.deltaY < 0 ? 1.1 : 1 / 1.1, ev.clientX, ev.clientY);
  }, { passive: false });
  window.addEventListener("resize", C.debounce(() => { if (state.fit) applyZoom(fitZoom(state.fit)); }, 150));

  // Glisser pour se déplacer ; un clic sans déplacement sélectionne l'élément.
  let drag = null;
  els.viewport.addEventListener("pointerdown", (ev) => {
    if (ev.button !== 0) return;
    drag = { x: ev.clientX, y: ev.clientY, left: els.viewport.scrollLeft, top: els.viewport.scrollTop, moved: false };
  });
  window.addEventListener("pointermove", (ev) => {
    if (!drag) return;
    const dx = ev.clientX - drag.x, dy = ev.clientY - drag.y;
    if (!drag.moved && Math.hypot(dx, dy) > 4) {
      drag.moved = true;
      els.viewport.classList.add("is-panning");
      hideTooltip();
    }
    if (drag.moved) {
      els.viewport.scrollLeft = drag.left - dx;
      els.viewport.scrollTop = drag.top - dy;
    }
  });
  window.addEventListener("pointerup", () => {
    if (drag && drag.moved) setTimeout(() => els.viewport.classList.remove("is-panning"), 0);
    drag = drag && drag.moved ? Object.assign(drag, { finished: true }) : null;
  });

  function findElement(id) {
    for (const kind of KINDS) {
      const index = (state.doc[kind] || []).findIndex((item) => item.id === id);
      if (index >= 0) return { kind, index, item: state.doc[kind][index] };
    }
    return null;
  }

  els.canvas.addEventListener("click", (ev) => {
    if (drag && drag.finished) { drag = null; return; }
    drag = null;
    const group = ev.target.closest("[data-ref]");
    if (!group) return;
    const found = findElement(group.getAttribute("data-ref").split("+")[0]);
    if (found) openDrawer(found.kind, found.index);
  });

  // ── Infobulle ────────────────────────────────────────────────
  function hideTooltip() { els.tooltip.hidden = true; }

  els.canvas.addEventListener("pointerover", (ev) => {
    if (drag && drag.moved) return;
    const group = ev.target.closest("[data-ref]");
    if (!group) { hideTooltip(); return; }
    const parts = [];
    for (const id of group.getAttribute("data-ref").split("+")) {
      const found = findElement(id);
      if (!found || found.kind === "tracks") continue;
      const item = found.item;
      let html = `<div class="tl-tooltip__date">${escapeHtml(state.dates[id] || "")}</div>`
        + `<strong>${escapeHtml(item.label)}</strong>`;
      if (item.description) html += `<p>${escapeHtml(item.description)}</p>`;
      if (item.date_text) html += `<p class="muted">${escapeHtml(T("timeline.ui.tooltip_course", { text: item.date_text }))}</p>`;
      if (item.source_quote) html += `<blockquote>${escapeHtml(item.source_quote)}</blockquote>`;
      if (state.quotes[id] === "not_found") html += `<p class="tl-tooltip__flag">⚠ ${escapeHtml(T("timeline.ui.quote_not_found"))}</p>`;
      if (state.quotes[id] === "fuzzy") html += `<p class="muted">≈ ${escapeHtml(T("timeline.ui.quote_fuzzy"))}</p>`;
      if (item.origin === "model") html += `<p class="tl-tooltip__flag">✦ ${escapeHtml(T("timeline.ui.badge_model"))}</p>`;
      parts.push(`<div class="tl-tooltip__item">${html}</div>`);
    }
    if (!parts.length) { hideTooltip(); return; }
    els.tooltip.innerHTML = parts.join("");
    els.tooltip.hidden = false;
    placeTooltip(ev);
  });
  els.canvas.addEventListener("pointermove", (ev) => { if (!els.tooltip.hidden) placeTooltip(ev); });
  els.canvas.addEventListener("pointerleave", hideTooltip);

  function placeTooltip(ev) {
    const host = els.panelPreview.getBoundingClientRect();
    const box = els.tooltip.getBoundingClientRect();
    let x = ev.clientX - host.left + 14;
    let y = ev.clientY - host.top + 14;
    if (x + box.width > host.width - 8) x = ev.clientX - host.left - box.width - 14;
    if (y + box.height > host.height - 8) y = ev.clientY - host.top - box.height - 14;
    els.tooltip.style.left = `${Math.max(8, x)}px`;
    els.tooltip.style.top = `${Math.max(8, y)}px`;
  }

  // ── Rail : l'éditeur structuré ──────────────────────────────
  function sortedIndexes(list, key) {
    return list.map((item, index) => index)
      .sort((a, b) => C.compareDates(list[a][key], list[b][key]) || a - b);
  }

  function badges(item) {
    const out = [];
    if (item.importance === 3) out.push(`<span class="badge tl-badge--pivot" title="${escapeHtml(T("timeline.ui.badge_pivot"))}">★</span>`);
    if (item.importance === 1) out.push(`<span class="badge" title="${escapeHtml(T("timeline.ui.badge_detail"))}">·</span>`);
    if (item.origin === "model") out.push(`<span class="badge" title="${escapeHtml(T("timeline.ui.badge_model"))}">✦</span>`);
    if (state.quotes[item.id] === "not_found") {
      out.push(`<span class="badge tl-badge--warn" title="${escapeHtml(T("timeline.ui.quote_not_found"))}">⚠</span>`);
    }
    if (state.quotes[item.id] === "fuzzy") {
      out.push(`<span class="badge" title="${escapeHtml(T("timeline.ui.quote_fuzzy"))}">≈</span>`);
    }
    if (state.notes[item.id]) {
      out.push(`<span class="badge" title="${escapeHtml(T("timeline.ui.badge_note", { n: state.notes[item.id] }))}">`
        + `n°${state.notes[item.id]}</span>`);
    }
    return out.join("");
  }

  function swatch(trackId) {
    const style = state.trackStyles[trackId];
    const color = style ? style.color : "";
    return `<span class="tl-swatch tl-swatch--${escapeHtml(style ? style.shape : "circle")}"`
      + (color ? ` style="--swatch:${escapeHtml(color)}"` : "") + " aria-hidden=\"true\"></span>";
  }

  function row(kind, index, dateText, extra) {
    const item = state.doc[kind][index];
    const active = state.editing && state.editing.kind === kind && state.editing.index === index;
    return `<li class="tl-item${active ? " active" : ""}"><button type="button" class="tl-row" data-kind="${kind}" data-index="${index}">`
      + (extra || "")
      + `<span class="tl-row__date">${escapeHtml(dateText)}</span>`
      + `<span class="tl-row__label">${escapeHtml(item.label || item.id)}</span>`
      + `<span class="tl-row__badges">${badges(item)}</span></button></li>`;
  }

  function section(kind, title, body, count) {
    const open = sectionOpen[kind] !== false;
    return `<details class="tl-section" data-section="${kind}"${open ? " open" : ""}>`
      + `<summary><span>${escapeHtml(title)}</span><span class="tl-section__count">${count}</span></summary>`
      + (count ? body : `<p class="tl-section__empty">${escapeHtml(T("timeline.ui.empty_section"))}</p>`)
      + "</details>";
  }
  const sectionOpen = {};

  // Paragraphe par paragraphe : la section Sources, avec l'état de chaque paragraphe
  // et le rapport de fusion.
  const STATUS_ICONS = { pending: "i-circle", ok: "i-check", empty: "i-minus", error: "i-alert" };

  function sourcesSection() {
    const done = state.chunks.filter((c) => c.status === "ok" || c.status === "empty").length;
    const rows = state.chunks.map((chunk) => {
      const active = chunk.id === state.currentChunk;
      const status = T(`timeline.ui.chunk_${chunk.status}`);
      return `<li class="tl-item${active ? " active" : ""}"><button type="button" class="tl-row tl-source" data-chunk="${chunk.id}"`
        + ` title="${escapeHtml(chunk.heading || `#${chunk.id}`)}">`
        + `<span class="tl-status tl-status--${chunk.status}" role="img" aria-label="${escapeHtml(status)}" title="${escapeHtml(status)}">`
        + `<svg width="14" height="14" aria-hidden="true"><use href="#${STATUS_ICONS[chunk.status] || "i-circle"}"></use></svg></span>`
        + `<span class="tl-row__label">${escapeHtml(chunk.title || `#${chunk.id}`)}</span>`
        + `<span class="tl-row__badges"><span class="badge${chunk.mentions ? "" : " tl-badge--muted"}"`
        + ` title="${escapeHtml(T("timeline.ui.mentions_title"))}">${escapeHtml(T("timeline.ui.mentions", { n: chunk.mentions }))}</span></span>`
        + "</button></li>";
    }).join("");
    return section("sources", T("timeline.ui.section_sources"),
      mergeSummary() + `<ul class="tl-list">${rows}</ul>` + mergeDetails(), `${done}/${state.chunks.length}`);
  }

  function mergeSummary() {
    const merge = state.merge;
    if (!merge || !(merge.chunks || []).length) return "";
    const bits = [T("timeline.ui.merge_elements", { n: merge.elements })];
    if (merge.merged) bits.push(T("timeline.ui.merge_duplicates", { n: merge.merged }));
    if ((merge.tracks || []).length) bits.push(T("timeline.ui.merge_tracks", { n: merge.tracks.length }));
    return `<p class="tl-merge">${escapeHtml(bits.join(" · "))}</p>`;
  }

  function mergeDetails() {
    const merge = state.merge;
    if (!merge) return "";
    // Les paragraphes sont désignés par leur rang dans la section Sources, pas par leur id de chunk.
    const position = (id) => {
      const index = state.chunks.findIndex((c) => c.id === id);
      return index >= 0 ? `#${index + 1}` : `#${id}`;
    };
    const items = (merge.duplicates || []).map((d) =>
      `<li class="tl-merge__item"><span class="tl-merge__what"><strong>${escapeHtml(d.label)}</strong>`
      + `<small>${escapeHtml(T("timeline.ui.merge_from", { chunks: d.chunks.map(position).join(", ") }))}</small></span>`
      // Deux ères identiques se chevauchent : séparées, la seconde serait aussitôt écartée.
      + (d.kind === "eras" ? ""
        : `<button type="button" class="btn sm ghost" data-${d.separated ? "join" : "separate"}="${escapeHtml(d.key)}">`
          + `${escapeHtml(T(d.separated ? "timeline.ui.merge_join" : "timeline.ui.merge_separate"))}</button>`)
      + "</li>");
    for (const era of merge.eras_dropped || []) {
      items.push(`<li class="tl-merge__item"><span class="tl-merge__what">${escapeHtml(
        T("timeline.ui.merge_era_dropped", { label: era.label, other: era.overlaps }))}</span></li>`);
    }
    if ((merge.tracks_folded || []).length) {
      items.push(`<li class="tl-merge__item"><span class="tl-merge__what">${escapeHtml(
        T("timeline.ui.merge_tracks_folded", { labels: merge.tracks_folded.join(", ") }))}</span></li>`);
    }
    if (!items.length) return "";
    return `<details class="tl-merges" data-section="merges"${sectionOpen.merges ? " open" : ""}>`
      + `<summary>${escapeHtml(T("timeline.ui.merge_details", { n: items.length }))}</summary>`
      + `<ul class="tl-merges__list">${items.join("")}</ul></details>`;
  }

  function renderEditor() {
    const doc = state.doc;
    const tracks = doc.tracks || [];
    const parts = [];
    if (perChunk()) parts.push(sourcesSection());

    // Pistes : renommer, couleur, ordre (flèches, accessibles au clavier).
    const trackRows = tracks.map((track, index) => {
      const active = state.editing && state.editing.kind === "tracks" && state.editing.index === index;
      return `<li class="tl-item${active ? " active" : ""}"><div class="tl-track">`
        + `<button type="button" class="tl-row" data-kind="tracks" data-index="${index}">${swatch(track.id)}`
        + `<span class="tl-row__label">${escapeHtml(track.label)}</span>`
        + `<span class="tl-row__badges"><span class="badge">${C.trackUsage(doc, track.id)}</span></span></button>`
        + `<button type="button" class="icon-btn tl-move" data-move="-1" data-index="${index}" aria-label="${escapeHtml(T("timeline.ui.move_up", { label: track.label }))}"${index === 0 ? " disabled" : ""}>`
        + `<svg width="14" height="14" aria-hidden="true"><use href="#i-up"></use></svg></button>`
        + `<button type="button" class="icon-btn tl-move" data-move="1" data-index="${index}" aria-label="${escapeHtml(T("timeline.ui.move_down", { label: track.label }))}"${index === tracks.length - 1 ? " disabled" : ""}>`
        + `<svg width="14" height="14" aria-hidden="true"><use href="#i-down"></use></svg></button>`
        + "</div></li>";
    }).join("");
    parts.push(section("tracks", T("timeline.ui.section_tracks"), `<ul class="tl-list">${trackRows}</ul>`, tracks.length));

    const eras = doc.eras || [];
    parts.push(section("eras", T("timeline.ui.section_eras"),
      `<ul class="tl-list">${sortedIndexes(eras, "start").map((i) =>
        row("eras", i, state.dates[eras[i].id] || `${eras[i].start}–${eras[i].end}`)).join("")}</ul>`, eras.length));

    const periods = doc.periods || [];
    parts.push(section("periods", T("timeline.ui.section_periods"),
      `<ul class="tl-list">${sortedIndexes(periods, "start").map((i) =>
        row("periods", i, state.dates[periods[i].id] || `${periods[i].start}–${periods[i].end}`,
            tracks.length ? swatch(periods[i].track) : "")).join("")}</ul>`, periods.length));

    // Évènements : regroupés par piste, triés par date.
    const events = doc.events || [];
    const groups = tracks.length ? tracks.map((t) => ({ id: t.id, label: t.label })) : [{ id: null, label: "" }];
    const orphans = events.some((e) => tracks.length && !tracks.some((t) => t.id === e.track));
    if (orphans) groups.push({ id: undefined, label: T("timeline.ui.no_track") });
    const eventBody = groups.map((group) => {
      const indexes = sortedIndexes(events, "date").filter((i) => {
        if (!tracks.length) return true;
        if (group.id === undefined) return !tracks.some((t) => t.id === events[i].track);
        return events[i].track === group.id;
      });
      if (!indexes.length) return "";
      const heading = group.label
        ? `<li class="tl-group">${swatch(group.id)}<span>${escapeHtml(group.label)}</span></li>` : "";
      return heading + indexes.map((i) => row("events", i, state.dates[events[i].id] || events[i].date)).join("");
    }).join("");
    parts.push(section("events", T("timeline.ui.section_events"), `<ul class="tl-list">${eventBody}</ul>`, events.length));

    els.editor.innerHTML = parts.join("");
  }

  els.editor.addEventListener("toggle", (ev) => {
    const section = ev.target.closest("[data-section]");
    if (section) sectionOpen[section.dataset.section] = section.open;
  }, true);

  els.editor.addEventListener("click", (ev) => {
    const move = ev.target.closest("[data-move]");
    if (move) { moveTrack(Number(move.dataset.index), Number(move.dataset.move)); return; }
    const source = ev.target.closest("[data-chunk]");
    if (source) {
      setRail(false);
      selectChunk(Number(source.dataset.chunk), { show: true });
      return;
    }
    const split = ev.target.closest("[data-separate], [data-join]");
    if (split) {
      mergeAction(split.dataset.separate ? { separate: split.dataset.separate } : { join: split.dataset.join });
      return;
    }
    const button = ev.target.closest(".tl-row");
    if (button) {
      setRail(false);           // en fenêtre étroite, le rail en tiroir laisse place à l'édition
      openDrawer(button.dataset.kind, Number(button.dataset.index));
    }
  });

  function moveTrack(index, delta) {
    const tracks = state.doc.tracks;
    const target = index + delta;
    if (target < 0 || target >= tracks.length) return;
    [tracks[index], tracks[target]] = [tracks[target], tracks[index]];
    // L'ordre affiché est celui du tableau ; un champ `order` existant le contredirait.
    if (tracks.some((t) => t.order !== undefined)) tracks.forEach((t, i) => { t.order = i + 1; });
    changed();
    const focus = els.editor.querySelector(`[data-move="${delta}"][data-index="${target}"]`)
      || els.editor.querySelector(`[data-index="${target}"]`);
    if (focus) focus.focus();
  }

  // ── Tiroir d'édition ─────────────────────────────────────────
  const PRECISIONS = ["day", "month", "year", "decade", "century", "millennium"];
  const KIND_TITLE = { tracks: "timeline.ui.kind_tracks", eras: "timeline.ui.kind_eras",
                       periods: "timeline.ui.kind_periods", events: "timeline.ui.kind_events" };

  function field(name, label, control, help) {
    return `<label class="tl-field" data-field="${name}"><span>${escapeHtml(label)}</span>${control}`
      + (help ? `<small class="tl-field__help" data-help="${name}">${escapeHtml(help)}</small>` : "")
      + `<small class="tl-field__error" data-error="${name}" hidden></small></label>`;
  }
  const input = (name, value, attrs) =>
    `<input type="text" name="${name}" value="${escapeHtml(value == null ? "" : value)}"${attrs || ""}>`;

  function select(name, value, options) {
    return `<select name="${name}">${options.map(([v, label]) =>
      `<option value="${escapeHtml(v)}"${String(v) === String(value == null ? "" : value) ? " selected" : ""}>${escapeHtml(label)}</option>`).join("")}</select>`;
  }

  function defaults(kind) {
    const doc = state.doc;
    const firstTrack = (doc.tracks || [])[0];
    if (kind === "tracks") return { id: C.uniqueId(doc, T("timeline.ui.kind_tracks")), label: "" };
    const item = { id: C.uniqueId(doc, T(KIND_TITLE[kind])), label: "", importance: 2, origin: "text" };
    if (kind !== "eras" && firstTrack) item.track = firstTrack.id;
    if (kind === "events") item.date = "";
    else { item.start = ""; item.end = ""; }
    return item;
  }

  function openDrawer(kind, index) {
    state.editing = { kind, index };
    const item = index === null ? defaults(kind) : clone(state.doc[kind][index]);
    const isNew = index === null;
    els.drawerTitle.textContent = isNew ? T(`timeline.ui.new_${kind}`) : `${T(KIND_TITLE[kind])} — ${item.label || item.id}`;
    const parts = [field("id", T("timeline.ui.field_id"), input("id", item.id, ' autocomplete="off" spellcheck="false"'),
                         T("timeline.ui.id_help"))];
    parts.push(field("label", T("timeline.ui.field_label"), input("label", item.label, ' maxlength="80"')));
    if (kind === "tracks") {
      const auto = !item.color;
      const style = state.trackStyles[item.id];
      parts.push(`<div class="tl-field"><span>${escapeHtml(T("timeline.ui.field_color"))}</span><div class="tl-color">`
        + `<input type="color" name="color" value="${escapeHtml(item.color || (style && style.color) || "#0371B1")}"${auto ? " disabled" : ""}>`
        + `<label class="tl-check"><input type="checkbox" name="color_auto"${auto ? " checked" : ""}> ${escapeHtml(T("timeline.ui.field_color_auto"))}</label>`
        + "</div></div>");
    } else {
      if (kind !== "eras" && (state.doc.tracks || []).length) {
        parts.push(field("track", T("timeline.ui.field_track"),
          select("track", item.track, state.doc.tracks.map((t) => [t.id, t.label]))));
      }
      const precision = select("precision", item.precision || "", [["", T("timeline.ui.precision_auto")]]
        .concat(PRECISIONS.map((p) => [p, T(`timeline.ui.precision_${p}`)])));
      if (kind === "events") {
        parts.push(field("date", T("timeline.ui.field_date"), input("date", item.date, ' spellcheck="false"'),
                         T("timeline.ui.date_help")));
      } else {
        parts.push(`<div class="tl-field-row">`
          + field("start", T("timeline.ui.field_start"), input("start", item.start, ' spellcheck="false"'), T("timeline.ui.date_help"))
          + field("end", T("timeline.ui.field_end"), input("end", item.end, ' spellcheck="false"'), T("timeline.ui.end_help"))
          + "</div>");
      }
      parts.push(`<div class="tl-field-row">${field("precision", T("timeline.ui.field_precision"), precision)}`
        + `<label class="tl-check tl-check--field"><input type="checkbox" name="approx"${item.approx ? " checked" : ""}> ${escapeHtml(T("timeline.ui.field_approx"))}</label></div>`);
      if (kind !== "eras") {
        const importance = [1, 2, 3].map((n) =>
          `<label class="tl-radio"><input type="radio" name="importance" value="${n}"${(item.importance || 2) === n ? " checked" : ""}>`
          + `<span>${escapeHtml(T(`timeline.ui.importance_${n}`))}</span></label>`).join("");
        parts.push(`<fieldset class="tl-field tl-importance"><legend>${escapeHtml(T("timeline.ui.field_importance"))}</legend>${importance}</fieldset>`);
      }
      parts.push(field("description", T("timeline.ui.field_description"),
        `<textarea name="description" rows="3" maxlength="600">${escapeHtml(item.description || "")}</textarea>`));
      if (kind !== "eras") {
        parts.push(field("date_text", T("timeline.ui.field_date_text"), input("date_text", item.date_text, ' maxlength="80"')));
        const quote = isNew ? null : state.quotes[item.id];
        parts.push(field("source_quote", T("timeline.ui.field_source_quote"),
          `<textarea name="source_quote" rows="2" maxlength="240">${escapeHtml(item.source_quote || "")}</textarea>`,
          quote ? T(`timeline.ui.quote_${quote}`) : ""));
        parts.push(field("origin", T("timeline.ui.field_origin"), select("origin", item.origin || "text", [
          ["text", T("timeline.ui.origin_text")], ["model", T("timeline.ui.origin_model")]])));
        parts.push(field("tags", T("timeline.ui.field_tags"), input("tags", (item.tags || []).join(", "))));
      }
    }
    els.form.innerHTML = parts.join("");
    els.form.dataset.kind = kind;
    els.form.dataset.idTouched = isNew ? "" : "1";
    els.form._item = item;
    showElementErrors(kind, index);
    $("tl-drawer-delete").hidden = isNew;
    els.drawer.hidden = false;
    document.body.classList.add("tl-drawer-open");
    for (const name of ["date", "start", "end"]) previewDate(name);
    renderEditor();
    const first = els.form.querySelector('input[name="label"]');
    if (first) first.focus();
  }

  function closeDrawer() {
    const editing = state.editing;
    els.drawer.hidden = true;
    document.body.classList.remove("tl-drawer-open");
    state.editing = null;
    renderEditor();
    // Le rail est redessiné (ici puis après la modification) : le focus clavier revient à
    // la ligne de l'élément, ou à sa section pour un élément nouveau, une fois tout redessiné.
    if (editing) setTimeout(() => returnFocus(editing), 0);
  }

  function returnFocus(editing) {
    if (document.activeElement && document.activeElement !== document.body
        && !els.drawer.contains(document.activeElement)) return;
    const row = editing.index === null ? null
      : els.editor.querySelector(`.tl-row[data-kind="${editing.kind}"][data-index="${editing.index}"]`);
    const target = row || els.editor.querySelector(`[data-section="${editing.kind}"] > summary`);
    if (target) target.focus();
  }

  /** Erreurs du dernier rapport qui concernent l'élément ouvert. */
  function showElementErrors(kind, index) {
    if (index === null || !state.report) return;
    const prefix = `/${kind}/${index}`;
    for (const error of state.report.errors || []) {
      if (error.path !== prefix && !error.path.startsWith(prefix + "/")) continue;
      const name = error.path.slice(prefix.length + 1).split("/")[0] || "label";
      const slot = els.form.querySelector(`[data-error="${name}"]`) || els.form.querySelector('[data-error="label"]');
      if (slot) { slot.textContent = error.message; slot.hidden = false; }
    }
  }

  // Aperçu d'une date du tiroir, formatée par le serveur (une seule logique de dates).
  // Les champs sont relus au moment de l'appel : le tiroir est reconstruit à chaque ouverture.
  async function fetchDatePreview(name) {
    const control = els.form.querySelector(`input[name="${name}"]`);
    const help = els.form.querySelector(`[data-help="${name}"]`);
    if (!control || !help || !control.value.trim()) return;
    const value = control.value.trim();
    const params = new URLSearchParams({
      value, lang: state.doc.lang || "",
      precision: (els.form.querySelector('select[name="precision"]') || {}).value || "",
      approx: (els.form.querySelector('input[name="approx"]') || {}).checked ? "1" : "0",
      end: name === "end" ? "1" : "0", as_of: state.doc.as_of || "",
    });
    try {
      const data = await (await fetch(`${URLS.date}?${params}`)).json();
      if (control.isConnected && control.value.trim() === value) {
        help.textContent = data.ok ? `→ ${data.text}` : data.message;
        help.classList.toggle("is-error", !data.ok);
      }
    } catch (e) { /* aperçu seulement */ }
  }
  const datePreviews = { date: C.debounce(fetchDatePreview, 200), start: C.debounce(fetchDatePreview, 200),
                         end: C.debounce(fetchDatePreview, 200) };

  function previewDate(name) {
    const control = els.form.querySelector(`input[name="${name}"]`);
    const help = els.form.querySelector(`[data-help="${name}"]`);
    if (!control || !help) return;
    if (!control.value.trim()) {
      help.textContent = T(name === "end" ? "timeline.ui.end_help" : "timeline.ui.date_help");
      help.classList.remove("is-error");
      return;
    }
    datePreviews[name](name);
  }

  els.form.addEventListener("input", (ev) => {
    const name = ev.target.name;
    // Nouvel élément : l'identifiant suit le libellé tant qu'on ne l'a pas modifié à la main.
    if (name === "id") els.form.dataset.idTouched = "1";
    if (name === "label" && !els.form.dataset.idTouched) {
      const kind = els.form.dataset.kind;
      els.form.querySelector('input[name="id"]').value =
        C.uniqueId(state.doc, ev.target.value || T(KIND_TITLE[kind]));
    }
    if (["date", "start", "end"].includes(name)) previewDate(name);
    if (name === "precision" || name === "approx") for (const n of ["date", "start", "end"]) previewDate(n);
    if (name === "color_auto") els.form.querySelector('input[name="color"]').disabled = ev.target.checked;
  });

  function readForm() {
    const kind = els.form.dataset.kind;
    const form = new FormData(els.form);
    const text = (name) => String(form.get(name) || "").trim();
    const item = clone(els.form._item);
    const set = (name, value) => { if (value === "" || value === null || value === undefined) delete item[name]; else item[name] = value; };
    set("id", text("id"));
    set("label", text("label"));
    if (kind === "tracks") {
      if (form.get("color_auto")) delete item.color;
      else set("color", text("color").toUpperCase());
      return item;
    }
    if (form.has("track")) set("track", text("track"));
    if (kind === "events") set("date", text("date"));
    else { set("start", text("start")); set("end", text("end")); }
    set("precision", text("precision"));
    item.approx = !!form.get("approx");
    if (kind !== "eras") item.importance = Number(form.get("importance") || 2);
    set("description", text("description"));
    if (kind !== "eras") {
      set("date_text", text("date_text"));
      set("source_quote", text("source_quote"));
      item.origin = text("origin") || "text";
      const tags = text("tags").split(",").map((t) => t.trim()).filter(Boolean);
      set("tags", tags.length ? tags : null);
    }
    return item;
  }

  els.form.addEventListener("submit", (ev) => {
    ev.preventDefault();
    const { kind, index } = state.editing;
    const item = readForm();
    const list = state.doc[kind] = state.doc[kind] || [];
    if (index === null) list.push(item);
    else {
      const previous = list[index].id;
      list[index] = item;
      if (previous !== item.id) C.renameId(state.doc, previous, item.id);
    }
    closeDrawer();
    changed();
  });

  $("tl-drawer-cancel").addEventListener("click", closeDrawer);
  $("tl-drawer-close").addEventListener("click", closeDrawer);
  $("tl-drawer-delete").addEventListener("click", () => {
    const { kind, index } = state.editing;
    const item = state.doc[kind][index];
    if (kind === "tracks") {
      const used = C.trackUsage(state.doc, item.id);
      if (used) { toast(T("timeline.ui.track_in_use", { count: used }), "err", 4000); return; }
    }
    if (!window.confirm(T("timeline.ui.delete_confirm", { label: item.label || item.id }))) return;
    state.doc[kind].splice(index, 1);
    closeDrawer();
    changed();
  });

  els.add.addEventListener("click", (ev) => {
    const button = ev.target.closest("[data-add]");
    if (!button) return;
    els.add.open = false;
    setRail(false);
    openDrawer(button.dataset.add, null);
  });

  // ── Vérifications : erreurs et avertissements ───────────────
  function issueLabel(path) {
    const target = C.elementAt(path);
    if (!target) return path || "/";
    const item = (state.doc[target.kind] || [])[target.index];
    return item ? (item.label || item.id) : path;
  }

  function renderIssues() {
    const report = state.report;
    const errors = report ? report.errors || [] : [];
    const warnings = (report ? report.warnings || [] : []).concat(state.layoutWarnings);
    if (!errors.length && !warnings.length) { els.issues.hidden = true; return; }
    els.issues.hidden = false;
    els.issues.classList.toggle("has-errors", errors.length > 0);
    els.issuesSummary.textContent = T("timeline.ui.issues_count", { errors: errors.length, warnings: warnings.length });
    if (errors.length) els.issues.open = true;
    const item = (entry, kind) => {
      const path = entry.path !== undefined ? entry.path : (entry.ref ? pathOf(entry.ref) : "");
      return `<li class="tl-issue tl-issue--${kind}"><button type="button" data-path="${escapeHtml(path || "")}">`
        + `<span class="tl-issue__where">${escapeHtml(path ? issueLabel(path) : T("timeline.ui.whole_timeline"))}</span>`
        + `<span>${escapeHtml(entry.message || entry.code)}</span>`
        + (entry.hint ? `<small>${escapeHtml(entry.hint)}</small>` : "") + "</button></li>";
    };
    els.issuesList.innerHTML = errors.map((e) => item(e, "error")).join("")
      + warnings.map((w) => item(w, "warning")).join("");
  }

  function pathOf(ref) {
    const found = findElement(String(ref).split("+")[0]);
    return found ? `/${found.kind}/${found.index}` : "";
  }

  els.issuesList.addEventListener("click", (ev) => {
    const button = ev.target.closest("[data-path]");
    if (!button) return;
    const target = C.elementAt(button.dataset.path);
    if (target && state.doc[target.kind] && state.doc[target.kind][target.index]) {
      openDrawer(target.kind, target.index);
    } else {
      setTab("json");
      focusPath(button.dataset.path);
    }
  });

  // ── Onglets ──────────────────────────────────────────────────
  let activeTab = "preview";
  function setTab(tab) {
    activeTab = tab;
    for (const button of els.tabs.querySelectorAll("[data-tab]")) {
      const on = button.dataset.tab === tab;
      button.classList.toggle("active", on);
      button.setAttribute("aria-selected", String(on));
      button.tabIndex = on ? 0 : -1;
    }
    els.panelPreview.hidden = tab !== "preview";
    els.panelJson.hidden = tab !== "json";
    if (els.panelPrompt) els.panelPrompt.hidden = tab !== "prompt";
    $("tl-panel-cards").hidden = tab !== "cards";
    els.tools.hidden = tab !== "preview";
    if (tab === "json" && !state.jsonDirty) els.json.value = C.serialize(state.doc);
    if (tab === "preview" && state.fit) applyZoom(fitZoom(state.fit));
    if (tab === "prompt" && state.prompt.url !== promptUrl()) loadPrompt();
    // Les autres scripts de la page (cartes) se chargent quand leur onglet s'ouvre.
    document.dispatchEvent(new CustomEvent("timeline:tab", { detail: { tab } }));
  }
  els.tabs.addEventListener("click", (ev) => {
    const button = ev.target.closest("[data-tab]");
    if (button) setTab(button.dataset.tab);
  });
  els.tabs.addEventListener("keydown", (ev) => {
    if (ev.key !== "ArrowLeft" && ev.key !== "ArrowRight") return;
    const tabs = [...els.tabs.querySelectorAll("[data-tab]")].map((b) => b.dataset.tab);
    const next = tabs[(tabs.indexOf(activeTab) + (ev.key === "ArrowRight" ? 1 : tabs.length - 1)) % tabs.length];
    setTab(next);
    els.tabs.querySelector(`[data-tab="${next}"]`).focus();
  });

  // Thème et densité de l'aperçu.
  function segChoice(container, attr, value) {
    for (const button of container.querySelectorAll(`[data-${attr}]`)) {
      const on = button.dataset[attr] === value;
      button.classList.toggle("active", on);
      button.setAttribute("aria-checked", String(on));
    }
  }
  $("tl-theme").addEventListener("click", (ev) => {
    const button = ev.target.closest("[data-theme]");
    if (!button) return;
    state.theme = button.dataset.theme;
    segChoice($("tl-theme"), "theme", state.theme);
    renderPreview();
  });
  $("tl-density").addEventListener("click", (ev) => {
    const button = ev.target.closest("[data-density]");
    if (!button) return;
    state.density = button.dataset.density;
    segChoice($("tl-density"), "density", state.density);
    renderPreview();
  });
  window.matchMedia("(prefers-color-scheme: dark)").addEventListener("change", () => {
    if (state.theme === "auto") renderPreview();
  });

  // ── Onglet JSON ──────────────────────────────────────────────
  els.json.addEventListener("input", () => {
    state.jsonDirty = true;
    els.jsonStatus.textContent = "";
    updateState();
  });

  function focusPath(path, params) {
    const text = els.json.value;
    let start, end;
    if (params && params.line) {
      start = end = C.lineColumnOffset(text, params.line, params.column || 1);
    } else {
      ({ start, end } = C.pointerRange(text, path));
    }
    els.json.focus();
    els.json.setSelectionRange(start, end);
    // Faire défiler jusqu'à la ligne sélectionnée.
    const line = text.slice(0, start).split("\n").length;
    const lineHeight = parseFloat(getComputedStyle(els.json).lineHeight) || 20;
    els.json.scrollTop = Math.max(0, (line - 3) * lineHeight);
  }

  function renderJsonErrors(report) {
    const errors = (report && report.errors) || [];
    els.jsonErrors.innerHTML = errors.map((e, i) =>
      `<li><button type="button" data-error-index="${i}"><code>${escapeHtml(e.path || "/")}</code>`
      + `<span>${escapeHtml(e.message)}</span>${e.hint ? `<small>${escapeHtml(e.hint)}</small>` : ""}</button></li>`).join("");
    els.jsonErrors._errors = errors;
  }

  els.jsonErrors.addEventListener("click", (ev) => {
    const button = ev.target.closest("[data-error-index]");
    if (!button) return;
    const error = els.jsonErrors._errors[Number(button.dataset.errorIndex)];
    focusPath(error.path, error.params);
  });

  /** Valide le texte de l'onglet JSON ; s'il est bon, il devient le document édité. */
  async function validateJson() {
    const { data } = await postJson(URLS.validate, { raw: els.json.value, lang: state.doc.lang });
    if (!data) { toast(T("timeline.ui.network_error"), "err"); return false; }
    renderJsonErrors(data);
    if (!data.ok) {
      els.jsonStatus.textContent = T("timeline.ui.json_invalid", { count: data.errors.length });
      els.jsonStatus.className = "tl-json-status--err";
      return false;
    }
    state.doc = data.normalized;
    state.jsonDirty = false;
    els.json.value = C.serialize(state.doc);
    els.jsonStatus.textContent = T("timeline.ui.json_valid");
    els.jsonStatus.className = "tl-json-status--ok";
    changed({ fromJson: true });
    return true;
  }
  $("tl-json-validate").addEventListener("click", validateJson);

  // ── Prompt : extraction, correction, paragraphe par paragraphe ──
  function perChunk() {
    return state.extraction.strategy === "per_chunk" && state.chunks.length > 0;
  }

  function chunkIndex() {
    return state.chunks.findIndex((c) => c.id === state.currentChunk);
  }

  /** L'URL du prompt à montrer : correction du dernier collage raté, ou extraction. */
  function promptUrl() {
    if (!hasSource) return null;
    const params = new URLSearchParams();
    if (state.correction) {
      if (state.correction.chunk !== null) params.set("chunk_id", state.correction.chunk);
      if (els.correctionWarnings.checked) params.set("warnings", "1");
      return `${URLS.correction}?${params}`;
    }
    params.set("mode", state.extraction.mode);
    params.set("skill", state.extraction.skill ? "1" : "0");
    if (perChunk() && state.currentChunk !== null) params.set("chunk_id", state.currentChunk);
    return `${URLS.prompt}?${params}`;
  }

  async function loadPrompt() {
    const url = promptUrl();
    if (!url) return "";
    const seq = ++state.promptSeq;
    let data = null;
    try { data = await (await fetch(url)).json(); } catch (e) { data = null; }
    if (seq !== state.promptSeq) return state.prompt.text;
    if (!data || !data.ok) {
      if (state.correction && data) {       // plus rien à corriger : retour au prompt d'extraction
        setCorrection(null);
        return loadPrompt();
      }
      state.prompt = { url: null, text: "" };
      els.promptText.textContent = (data && data.error) || T("timeline.ui.network_error");
      return "";
    }
    state.prompt = { url, text: data.prompt };
    els.promptText.textContent = data.prompt;
    els.promptSize.textContent = data.tokens
      ? T("timeline.ui.prompt_tokens", { n: data.tokens.toLocaleString(document.documentElement.lang || undefined) }) : "";
    if (state.correction) {
      els.correctionSummary.textContent = T("timeline.ui.correction_summary", { errors: data.errors, warnings: data.warnings });
    }
    return data.prompt;
  }

  function renderPromptChrome() {
    if (!hasSource) return;
    segChoice(els.mode, "mode", state.extraction.mode);
    els.skill.checked = !!state.extraction.skill;
    els.correction.hidden = !state.correction;
    if (els.copyPromptLabel) {
      els.copyPromptLabel.textContent = T(state.correction ? "timeline.ui.copy_correction" : "timeline.ui.copy_prompt");
    }
    if (els.jsonCorrection) els.jsonCorrection.hidden = !(state.correction && state.correction.chunk === null);
    const nav = perChunk();
    els.chunkNav.hidden = !nav;
    if (nav) {
      const index = chunkIndex();
      const chunk = state.chunks[index];
      els.chunkLabel.textContent = T("timeline.ui.chunk_position", { n: index + 1, total: state.chunks.length, title: chunk.title });
      els.chunkLabel.title = chunk.heading;
      if (els.dockCounter) els.dockCounter.textContent = `${index + 1}/${state.chunks.length}`;
      for (const button of document.querySelectorAll("[data-chunk-step]")) {
        const step = Number(button.dataset.chunkStep);
        button.disabled = index + step < 0 || index + step >= state.chunks.length;
      }
    }
    const fromCourse = ["project", "chapter", "chunk"].includes(DATA.source.kind);
    els.promptNote.hidden = !fromCourse || DATA.project_exists;
    els.promptNote.textContent = T("timeline.ui.source_deleted");
  }

  function setCorrection(correction) {
    state.correction = correction;
    if (!correction) renderChunkErrors(null);
    renderPromptChrome();
  }

  function renderChunkErrors(report) {
    if (!els.chunkErrors) return;
    const errors = (report && report.errors) || [];
    els.chunkErrors.innerHTML = errors.map((e) =>
      `<li><button type="button" tabindex="-1"><code>${escapeHtml(e.path || "/")}</code>`
      + `<span>${escapeHtml(e.message)}</span>${e.hint ? `<small>${escapeHtml(e.hint)}</small>` : ""}</button></li>`).join("");
  }

  function selectChunk(id, { show = false } = {}) {
    const chunk = state.chunks.find((c) => c.id === id);
    if (!chunk) return;
    state.currentChunk = id;
    setCorrection(chunk.status === "error" ? { chunk: id } : null);
    renderEditor();
    if (show) setTab("prompt");
    loadPrompt();
  }

  function stepChunk(step) {
    const next = state.chunks[chunkIndex() + step];
    if (next) selectChunk(next.id);
  }

  async function copyText(text) {
    try {
      await navigator.clipboard.writeText(text);
      return true;
    } catch (e) { /* repli ci-dessous */ }
    const area = document.createElement("textarea");
    area.value = text;
    area.style.cssText = "position:fixed;top:0;left:0;opacity:0";
    document.body.appendChild(area);
    area.select();
    let ok = false;
    try { ok = document.execCommand("copy"); } catch (e) { ok = false; }
    area.remove();
    return ok;
  }

  async function copyPrompt() {
    if (!hasSource) return;
    const text = state.prompt.url === promptUrl() && state.prompt.text ? state.prompt.text : await loadPrompt();
    if (!text) return;
    if (await copyText(text)) {
      toast(T(state.correction ? "timeline.ui.correction_copied" : "timeline.ui.prompt_copied"), "ok");
      return;
    }
    // Presse-papiers refusé : le texte sélectionné à l'écran, pour un Ctrl+C.
    setTab("prompt");
    const range = document.createRange();
    range.selectNodeContents(els.promptText);
    const selection = window.getSelection();
    selection.removeAllRanges();
    selection.addRange(range);
    toast(T("timeline.ui.copy_failed"), "err", 4000);
  }

  function saveExtractionSettings() {
    postJson(URLS.api, { extraction: { mode: state.extraction.mode, skill: !!state.extraction.skill } })
      .catch(() => toast(T("timeline.ui.network_error"), "err"));
  }

  if (hasSource) {
    els.mode.addEventListener("click", (ev) => {
      const button = ev.target.closest("[data-mode]");
      if (!button || button.dataset.mode === state.extraction.mode) return;
      state.extraction.mode = button.dataset.mode;
      renderPromptChrome();
      saveExtractionSettings();
      if (!state.correction) loadPrompt();
    });
    els.skill.addEventListener("change", () => {
      state.extraction.skill = els.skill.checked;
      saveExtractionSettings();
      if (!state.correction) loadPrompt();
    });
    els.skillCopy.addEventListener("click", async () => {
      let text = "";
      try {
        text = await (await fetch(`${URLS.skill}?${new URLSearchParams({ lang: state.doc.lang || "" })}`)).text();
      } catch (e) { toast(T("timeline.ui.network_error"), "err"); return; }
      toast(T(await copyText(text) ? "timeline.ui.skill_copied" : "timeline.ui.copy_failed"),
            text ? "ok" : "err", 5000);
    });
    els.correctionWarnings.addEventListener("change", loadPrompt);
    els.correctionBack.addEventListener("click", () => { setCorrection(null); loadPrompt(); });
    if (els.jsonCorrection) els.jsonCorrection.addEventListener("click", () => setTab("prompt"));
    if (els.copyPrompt) els.copyPrompt.addEventListener("click", copyPrompt);
    const emptyPrompt = $("tl-empty-prompt");
    if (emptyPrompt) emptyPrompt.addEventListener("click", copyPrompt);
    for (const button of document.querySelectorAll("[data-chunk-step]")) {
      button.addEventListener("click", () => stepChunk(Number(button.dataset.chunkStep)));
    }
  }

  // ── Fusion (paragraphe par paragraphe) ──────────────────────
  /** Réponse d'un collage de paragraphe ou d'une fusion : états, document fusionné, rapport. */
  function applyMerge(data) {
    if (data.chunks) state.chunks = data.chunks;
    if ("merge" in data) state.merge = data.merge;
    if (data.merged) {
      state.doc = data.data ? clone(data.data) : skeleton();
      state.saved = C.serialize(state.doc);
      state.jsonDirty = false;
      els.json.value = C.serialize(state.doc);
    }
    renderEditor();
    updateState();
    renderPromptChrome();
    scheduleRender();
  }

  /** Refait la fusion sur le serveur ; les retouches ne sont écrasées qu'après confirmation. */
  async function mergeAction(body) {
    if (isDirty() && !window.confirm(T("timeline.ui.merge_unsaved_confirm"))) return;
    let { status, data } = await postJson(URLS.merge, body);
    if (status === 409) {
      if (!window.confirm(T("timeline.ui.merge_replace_confirm"))) return;
      ({ status, data } = await postJson(URLS.merge, Object.assign({}, body, { force: true })));
    }
    if (!data || !data.ok) { toast((data && data.error) || T("timeline.ui.network_error"), "err"); return; }
    applyMerge(data);
    toast(T("timeline.ui.merge_done"), "ok");
  }

  // ── Dock : coller, valider et enregistrer ───────────────────
  async function readClipboard() {
    try {
      return await navigator.clipboard.readText();
    } catch (e) {
      // Lecture refusée : Ctrl+V reste possible (événement « paste », sans permission).
      toast(T("timeline.ui.clipboard_failed"), "err", 5000);
      return null;
    }
  }

  async function paste() {
    const text = await readClipboard();
    if (text !== null) await pasteText(text);
  }

  // Ctrl+V hors d'un champ de saisie colle comme le bouton « Coller le JSON ».
  document.addEventListener("paste", (ev) => {
    if (ev.target.closest && ev.target.closest("input, textarea, select, [contenteditable]")) return;
    const text = ev.clipboardData ? ev.clipboardData.getData("text") : "";
    if (!text) return;
    ev.preventDefault();
    pasteText(text);
  });

  async function pasteText(text) {
    if (!text.trim()) { toast(T("timeline.ui.clipboard_empty"), "err"); return; }
    if (perChunk()) { await pasteChunk(text); return; }
    if (isDirty() && !window.confirm(T("timeline.ui.paste_replace_confirm"))) return;
    // Le collage part au serveur : il est gardé (audit, prompt de correction) et
    // enregistré s'il est valide.
    const { data } = await postJson(URLS.api, { raw: text });
    if (!data || !data.report) { toast(T("timeline.ui.network_error"), "err"); return; }
    if (data.ok) {
      state.doc = clone(data.report.normalized);
      state.saved = C.serialize(state.doc);
      state.jsonDirty = false;
      els.json.value = C.serialize(state.doc);
      renderJsonErrors(null);
      setCorrection(null);
      changed({ fromJson: true });
      setTab("preview");
      toast(T("timeline.ui.pasted_saved"), "ok");
      return;
    }
    els.json.value = text;
    state.jsonDirty = true;
    updateState();
    renderJsonErrors(data.report);
    els.jsonStatus.textContent = T("timeline.ui.json_invalid", { count: data.report.errors.length });
    els.jsonStatus.className = "tl-json-status--err";
    if (hasSource) setCorrection({ chunk: null });
    setTab("json");
    const first = (els.jsonErrors._errors || [])[0];
    if (first) focusPath(first.path, first.params);
  }

  async function pasteChunk(text) {
    const chunkId = state.currentChunk;
    if (isDirty() && !window.confirm(T("timeline.ui.merge_unsaved_confirm"))) return;
    let { status, data } = await postJson(URLS.api, { raw: text, chunk_id: chunkId });
    if (!data || !data.chunk) { toast((data && data.error) || T("timeline.ui.network_error"), "err"); return; }
    if (data.edited) {
      // Le paragraphe est gardé ; la frise, retouchée depuis la dernière fusion, attend l'accord.
      const pasted = data.chunk;
      applyMerge(data);
      if (!window.confirm(T("timeline.ui.merge_replace_confirm"))) return;
      ({ status, data } = await postJson(URLS.merge, { force: true }));
      if (!data || !data.ok) { toast(T("timeline.ui.network_error"), "err"); return; }
      data.chunk = pasted;
    }
    applyMerge(data);
    const chunkStatus = data.chunk.status;
    if (chunkStatus === "error") {
      setCorrection({ chunk: chunkId });
      renderChunkErrors(data.report);
      setTab("prompt");
      loadPrompt();
      toast(T("timeline.ui.chunk_paste_failed", { count: data.report.errors.length }), "err", 4000);
      return;
    }
    setCorrection(null);
    const index = state.chunks.findIndex((c) => c.id === chunkId);
    toast(T(chunkStatus === "empty" ? "timeline.ui.chunk_pasted_empty" : "timeline.ui.chunk_pasted",
            { n: index + 1 }), "ok");
    const next = C.nextPendingChunk(state.chunks, chunkId);
    if (next) selectChunk(next.id);
    else { renderEditor(); toast(T("timeline.ui.chunks_done"), "ok", 4000); }
    if (activeTab === "prompt" || activeTab === "json") setTab("preview");
  }
  $("tl-paste").addEventListener("click", paste);
  $("tl-empty-paste").addEventListener("click", paste);
  $("tl-empty-json").addEventListener("click", () => { setTab("json"); els.json.focus(); });

  async function save() {
    if (state.jsonDirty && !(await validateJson())) {
      setTab("json");
      toast(T("timeline.ui.save_failed"), "err", 4000);
      return false;
    }
    const { status, data } = await postJson(URLS.api, { data: state.doc, options: { density: state.density } });
    if (status === 200 && data && data.ok) {
      state.saved = C.serialize(state.doc);
      updateState();
      toast(T("timeline.ui.saved"), "ok");
      document.dispatchEvent(new CustomEvent("timeline:saved"));
      return true;
    }
    if (data && data.report) { state.report = data.report; renderIssues(); }
    toast(T("timeline.ui.save_failed"), "err", 4000);
    return false;
  }
  $("tl-save").addEventListener("click", save);

  // Ce que les autres scripts de la page (export) ont besoin de savoir ou de faire.
  window.TimelinePage = {
    isDirty,
    save,
    setTab,
    hasContent: () => hasContent(state.doc),
    density: () => state.density,
  };

  document.addEventListener("keydown", (ev) => {
    const mod = ev.ctrlKey || ev.metaKey;
    if (mod && ev.key === "Enter") { ev.preventDefault(); save(); return; }
    if (mod && ev.shiftKey && ev.key.toLowerCase() === "c" && hasSource) { ev.preventDefault(); copyPrompt(); return; }
    if (mod && ev.shiftKey && ev.key.toLowerCase() === "v") { ev.preventDefault(); paste(); return; }
    if (ev.altKey && perChunk() && (ev.key === "ArrowLeft" || ev.key === "ArrowRight")) {
      ev.preventDefault();
      stepChunk(ev.key === "ArrowLeft" ? -1 : 1);
      return;
    }
    if (ev.key === "Escape") {
      if (!els.drawer.hidden) { closeDrawer(); return; }
      hideTooltip();
      setRail(false);
    }
    if ((ev.ctrlKey || ev.metaKey) && !els.panelPreview.hidden) {
      if (ev.key === "+" || ev.key === "=") { ev.preventDefault(); zoomBy(1.25); }
      if (ev.key === "-") { ev.preventDefault(); zoomBy(0.8); }
      if (ev.key === "0") { ev.preventDefault(); state.fit = "width"; applyZoom(fitZoom("width")); }
    }
  });

  // Garde de sortie : rien ne se perd sans avertissement.
  window.addEventListener("beforeunload", (ev) => {
    if (!isDirty()) return;
    ev.preventDefault();
    ev.returnValue = "";
  });

  // ── Rail en tiroir (petites fenêtres) ────────────────────────
  function setRail(open) {
    document.body.classList.toggle("rail-open", open);
    els.railToggle.setAttribute("aria-expanded", String(open));
  }
  els.railToggle.addEventListener("click", () => setRail(!document.body.classList.contains("rail-open")));
  els.railClose.addEventListener("click", () => setRail(false));
  els.railScrim.addEventListener("click", () => setRail(false));

  // ── Démarrage ────────────────────────────────────────────────
  segChoice($("tl-density"), "density", state.density);
  if (perChunk()) {
    const first = state.chunks.find((c) => c.status === "pending" && c.mentions > 0)
      || state.chunks.find((c) => c.status === "pending" || c.status === "error") || state.chunks[0];
    state.currentChunk = first.id;
    if (first.status === "error") state.correction = { chunk: first.id };
  }
  // En paragraphe par paragraphe, le dernier collage est celui d'un paragraphe, pas la frise.
  els.json.value = DATA.data || perChunk() ? C.serialize(state.doc) : (DATA.last_raw || "");
  updateState();
  renderEditor();
  if (hasSource && !DATA.data && (!DATA.last_raw || perChunk())) {
    // Frise tout juste créée depuis un cours ou un texte : on commence par le prompt.
    renderPromptChrome();
    setTab("prompt");
    renderPreview();
  } else if (!DATA.data && DATA.last_raw) {
    // Import forcé ou collage invalide : on montre tout de suite ce qui ne va pas.
    if (hasSource) state.correction = { chunk: null };
    renderPromptChrome();
    state.jsonDirty = true;
    updateState();
    setTab("json");
    validateJson().then((ok) => {
      const first = (els.jsonErrors._errors || [])[0];
      if (!ok && first) focusPath(first.path, first.params);
    });
  } else {
    renderPromptChrome();
    renderPreview();
  }
})();
