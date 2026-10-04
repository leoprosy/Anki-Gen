/* ============================================================
   Ankigen — page frise : modale d'export (§9)
   PNG, JPEG, WebP, PDF (raster 300 dpi), SVG et JSON, depuis la
   frise ENREGISTRÉE. La modale annonce la miniature, les
   dimensions finales et le poids estimé ; l'export se passe comme
   celui des cartes (téléchargement + copie dans le dossier
   d'export). La copie de l'image dans le presse-papiers n'est
   proposée que si le navigateur sait le faire (D6).
   ============================================================ */
(() => {
  const dialog = document.getElementById("tl-export");
  if (!dialog) return;
  const URLS = window.__TIMELINE_URLS__;
  const DATA = window.__TIMELINE__;
  const T = (key, params) => window.T(key, params);
  const $ = (id) => document.getElementById(id);
  const toast = (message, kind, ms) => window.toast && window.toast(message, kind, ms);
  const escapeHtml = (s) => String(s == null ? "" : s).replace(/[&<>"']/g, (c) => (
    { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
  const number = (n, digits = 0) => Number(n).toLocaleString(document.documentElement.lang || undefined,
    { maximumFractionDigits: digits });
  const page = () => window.TimelinePage || { isDirty: () => false, save: async () => true, hasContent: () => true };

  const RASTER = ["png", "jpeg", "webp"];
  const STORAGE_KEY = "ankigen.timeline.export";
  const DEFAULTS = {
    fmt: "png", theme: "light", density: (DATA.render_options && DATA.render_options.density) || "compact",
    width_mode: "auto", width_px: 1200, scale: 2, quality: 90, transparent: false, lossless: false,
    page: "fit", orientation: "landscape", margin: 10, embed_font: true, unverified: false,
  };
  // Les options restent d'un export à l'autre (confort du lecteur, pas un réglage de la frise).
  let options = Object.assign({}, DEFAULTS, readStored());
  let seq = 0;

  function readStored() {
    try { return JSON.parse(window.localStorage.getItem(STORAGE_KEY) || "{}") || {}; } catch (e) { return {}; }
  }
  function store() {
    try { window.localStorage.setItem(STORAGE_KEY, JSON.stringify(options)); } catch (e) { /* facultatif */ }
  }

  const els = {
    open: $("tl-export-open"), close: $("tl-export-close"), cancel: $("tl-export-cancel"), go: $("tl-export-go"),
    copy: $("tl-export-copy"), thumb: $("tl-export-thumb"), dims: $("tl-export-dims"),
    warnings: $("tl-export-warnings"), status: $("tl-export-status"), unsaved: $("tl-export-unsaved"),
    save: $("tl-export-save"), width: $("tl-export-width"), quality: $("tl-export-quality"),
    qualityValue: $("tl-export-quality-value"), margin: $("tl-export-margin"),
  };
  const SEGMENTS = { fmt: "tl-export-format", theme: "tl-export-theme", density: "tl-export-density",
                     width_mode: "tl-export-width-mode", scale: "tl-export-scale", page: "tl-export-page",
                     orientation: "tl-export-orientation" };
  const CHECKS = { transparent: "tl-export-transparent", lossless: "tl-export-lossless",
                   embed_font: "tl-export-embed", unverified: "tl-export-unverified" };
  const canCopyImage = !!(window.ClipboardItem && navigator.clipboard && navigator.clipboard.write);

  // ── Affichage des options ────────────────────────────────────
  function render() {
    for (const [key, id] of Object.entries(SEGMENTS)) {
      for (const button of $(id).querySelectorAll("[data-value]")) {
        const on = button.dataset.value === String(options[key]);
        button.classList.toggle("active", on);
        button.setAttribute("aria-checked", String(on));
      }
    }
    for (const [key, id] of Object.entries(CHECKS)) if ($(id)) $(id).checked = !!options[key];
    els.width.value = options.width_px;
    els.width.disabled = options.width_mode !== "fixed";
    els.quality.value = options.quality;
    els.qualityValue.textContent = options.quality;
    els.margin.value = options.margin;
    // L'orientation n'a de sens que pour une page A4 ou A3.
    for (const button of $("tl-export-orientation").querySelectorAll("button")) button.disabled = options.page === "fit";
    for (const node of dialog.querySelectorAll("[data-for]")) {
      node.hidden = !node.dataset.for.split(" ").includes(options.fmt);
    }
    els.copy.hidden = !(canCopyImage && RASTER.includes(options.fmt));
    els.unsaved.hidden = !page().isDirty();
  }

  function query() {
    const params = new URLSearchParams();
    for (const key of ["theme", "density", "width_mode", "width_px", "scale", "quality", "page", "orientation", "margin"]) {
      params.set(key, options[key]);
    }
    for (const key of Object.keys(CHECKS)) params.set(key, options[key] ? "1" : "0");
    return params;
  }

  function size(bytes) {
    if (bytes >= 1024 * 1024) return T("timeline.ui.export_size_mb", { n: number(bytes / 1024 / 1024, 1) });
    return T("timeline.ui.export_size_kb", { n: number(Math.max(1, Math.round(bytes / 1024))) });
  }

  // ── Aperçu : miniature, dimensions, poids ───────────────────
  async function preview() {
    const mine = ++seq;
    els.thumb.classList.add("is-busy");
    let data = null;
    try {
      const response = await fetch(URLS.exportPreview, {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ fmt: options.fmt, options: Object.fromEntries(query()) }),
      });
      data = await response.json();
    } catch (e) { data = null; }
    if (mine !== seq) return;
    els.thumb.classList.remove("is-busy");
    if (!data || !data.ok) {
      els.thumb.innerHTML = "";
      els.dims.textContent = (data && data.error) || T("timeline.ui.network_error");
      els.go.disabled = true;
      els.copy.disabled = true;
      return;
    }
    els.go.disabled = false;
    els.copy.disabled = false;
    els.thumb.innerHTML = data.svg;
    const out = data.output;
    const parts = [];
    if (options.fmt === "pdf") {
      const name = options.page === "fit" ? T("timeline.ui.export_page_fit") : options.page.toUpperCase();
      parts.push(T("timeline.ui.export_dims_pdf", { page: name, width: number(out.page_mm[0]), height: number(out.page_mm[1]),
                                                     dpi: out.dpi, fit: out.fit }));
    } else if (out.width) {
      parts.push(T("timeline.ui.export_dims_px", { width: number(out.width), height: number(out.height) }));
    }
    parts.push(size(out.bytes));
    parts.push(data.filename);
    els.dims.textContent = parts.join(" · ");
    els.warnings.innerHTML = (data.warnings || []).map((w) => `<li>${escapeHtml(w.message)}</li>`).join("");
  }
  const schedulePreview = (window.TimelineCore ? window.TimelineCore.debounce(preview, 250) : preview);

  function changed() {
    store();
    render();
    schedulePreview();
  }

  // ── Export et copie ──────────────────────────────────────────
  function exportUrl(fmt, extra) {
    const params = query();
    if (extra) for (const [key, value] of Object.entries(extra)) params.set(key, value);
    return `${URLS.export.replace("FORMAT", fmt)}?${params}`;
  }

  // Une notification passerait sous le fond de la modale (couche supérieure du <dialog>) :
  // le résultat s'affiche dans sa ligne d'état. Les avertissements y sont déjà listés.
  function status(text, kind) {
    els.status.textContent = text || "";
    els.status.title = text || "";
    els.status.classList.toggle("is-error", kind === "err");
    els.status.classList.toggle("is-ok", kind === "ok");
  }

  /** Comme l'export des cartes : téléchargement, et chemin de la copie dans le dossier d'export. */
  async function runExport() {
    els.go.disabled = true;
    status(T("timeline.ui.export_running"));
    try {
      const response = await fetch(exportUrl(options.fmt));
      if (!response.ok) throw new Error("export");
      const blob = await response.blob();
      const name = (response.headers.get("Content-Disposition") || "")
        .split("filename=").pop().replace(/["';]/g, "") || "timeline";
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
      if (error) status(decodeURIComponent(error), "err");
      else if (path) status(T("timeline.ui.export_done", { path: decodeURIComponent(path) }), "ok");
      else status("");
    } catch (e) {
      status(T("timeline.ui.export_failed"), "err");
    } finally {
      els.go.disabled = false;
    }
  }

  /**
   * Copie l'image en PNG. Le blob est d'abord passé à ClipboardItem comme une
   * promesse : l'écriture reste attachée au clic, même si le rendu prend du temps.
   * Un moteur qui refuse cette forme reçoit ensuite le blob lui-même (la forme
   * validée dans WebView2, spike S8).
   */
  async function copyImage() {
    const url = exportUrl("png", { to: "clipboard", transparent: "0" });
    const blob = fetch(url).then((response) => {
      if (!response.ok) throw new Error("export");
      return response.blob();
    });
    els.copy.disabled = true;
    status(T("timeline.ui.export_running"));
    try {
      try {
        await navigator.clipboard.write([new window.ClipboardItem({ "image/png": blob })]);
      } catch (e) {
        await navigator.clipboard.write([new window.ClipboardItem({ "image/png": await blob })]);
      }
      status(T("timeline.ui.export_copied"), "ok");
    } catch (e) {
      status(T("timeline.ui.export_copy_failed"), "err");
    } finally {
      els.copy.disabled = false;
    }
  }

  // ── Écouteurs ────────────────────────────────────────────────
  for (const [key, id] of Object.entries(SEGMENTS)) {
    $(id).addEventListener("click", (ev) => {
      const button = ev.target.closest("[data-value]");
      if (!button || button.disabled) return;
      options[key] = key === "scale" ? Number(button.dataset.value) : button.dataset.value;
      changed();
    });
  }
  for (const [key, id] of Object.entries(CHECKS)) {
    if ($(id)) $(id).addEventListener("change", (ev) => { options[key] = ev.target.checked; changed(); });
  }
  els.width.addEventListener("change", () => {
    options.width_px = Math.min(12000, Math.max(900, Math.round(Number(els.width.value) || 1200)));
    changed();
  });
  els.quality.addEventListener("input", () => { els.qualityValue.textContent = els.quality.value; });
  els.quality.addEventListener("change", () => { options.quality = Number(els.quality.value); changed(); });
  els.margin.addEventListener("change", () => {
    options.margin = Math.min(30, Math.max(0, Math.round(Number(els.margin.value) || 0)));
    changed();
  });
  els.save.addEventListener("click", async () => {
    if (await page().save()) { render(); schedulePreview(); }
  });
  els.go.addEventListener("click", runExport);
  els.copy.addEventListener("click", copyImage);
  els.close.addEventListener("click", () => dialog.close());
  els.cancel.addEventListener("click", () => dialog.close());
  dialog.addEventListener("click", (ev) => { if (ev.target === dialog) dialog.close(); });
  els.open.addEventListener("click", () => {
    if (!page().hasContent() && !DATA.data) { toast(T("timeline.api.empty"), "err"); return; }
    render();
    dialog.showModal();
    preview();
  });
})();
