/* ============================================================
   Ankigen — fonctions pures de la page frise
   Sans DOM ni réseau : testées sous Node (tests/test_timeline_ui.js),
   exposées au navigateur sous window.TimelineCore.
   ============================================================ */
(function (root, factory) {
  if (typeof module === "object" && module.exports) module.exports = factory();
  else root.TimelineCore = factory();
})(typeof self !== "undefined" ? self : this, function () {
  "use strict";

  // Ordre canonique des clés : le même que timeline_schema.py, pour que le JSON
  // affiché soit celui que le serveur enregistrera.
  const COMMON = ["precision", "approx", "importance", "origin", "description", "date_text",
                  "source_quote", "tags", "color"];
  const ORDER = {
    root: ["schema", "title", "subtitle", "lang", "as_of", "tracks", "eras", "periods", "events", "links"],
    tracks: ["id", "label", "color", "order"],
    eras: ["id", "label", "start", "end"].concat(COMMON),
    periods: ["id", "track", "label", "start", "end"].concat(COMMON),
    events: ["id", "track", "label", "date"].concat(COMMON),
    links: ["from", "to", "label"],
  };

  function ordered(object, keys) {
    const out = {};
    for (const key of keys) if (Object.prototype.hasOwnProperty.call(object, key)) out[key] = object[key];
    for (const key of Object.keys(object)) if (!(key in out)) out[key] = object[key];
    return out;
  }

  /** Document → JSON indenté, clés dans l'ordre canonique. */
  function serialize(doc) {
    if (!doc || typeof doc !== "object") return "";
    const out = ordered(doc, ORDER.root);
    for (const kind of ["tracks", "eras", "periods", "events", "links"]) {
      if (Array.isArray(out[kind])) {
        out[kind] = out[kind].map((item) =>
          item && typeof item === "object" && !Array.isArray(item) ? ordered(item, ORDER[kind]) : item);
      }
    }
    return JSON.stringify(out, null, 2);
  }

  /** Anti-rebond : `fn` ne part qu'après `wait` ms sans nouvel appel. */
  function debounce(fn, wait, timers) {
    const set = (timers && timers.setTimeout) || setTimeout;
    const clear = (timers && timers.clearTimeout) || clearTimeout;
    let handle = null;
    function debounced(...args) {
      if (handle !== null) clear(handle);
      handle = set(() => { handle = null; fn(...args); }, wait);
    }
    debounced.cancel = () => { if (handle !== null) clear(handle); handle = null; };
    debounced.flush = (...args) => { debounced.cancel(); fn(...args); };
    return debounced;
  }

  /**
   * Un seul appel asynchrone en vol : le premier part aussitôt, et tous ceux qui
   * arrivent pendant qu'il tourne se regroupent en un seul appel, lancé dès qu'il
   * finit. Une modification isolée se redessine sans attendre ; pendant la frappe,
   * le rendu suit au rythme du serveur, sans file d'attente.
   */
  function singleFlight(fn) {
    let running = false;
    let again = false;
    return async function run() {
      if (running) { again = true; return; }
      running = true;
      try {
        do {
          again = false;
          try { await fn(); } catch (_) { /* l'appelant signale ses propres erreurs */ }
        } while (again);
      } finally {
        running = false;
      }
    };
  }

  /** "/events/3/date" → ["events", "3", "date"] (RFC 6901 : ~1 → /, ~0 → ~). */
  function parsePointer(pointer) {
    if (!pointer) return [];
    return pointer.split("/").slice(1).map((t) => t.replace(/~1/g, "/").replace(/~0/g, "~"));
  }

  /** Élément du document désigné par un chemin : { kind, index } ou null. */
  function elementAt(pointer) {
    const tokens = parsePointer(pointer);
    if (tokens.length >= 2 && ORDER[tokens[0]] && tokens[0] !== "root" && /^\d+$/.test(tokens[1])) {
      return { kind: tokens[0], index: Number(tokens[1]) };
    }
    return null;
  }

  // ── Positions dans un texte JSON (même invalide) ───────────────
  // Arbre { type, start, end, children } construit au fil de la lecture : si le
  // texte casse en route, ce qui a été lu reste utilisable pour placer le curseur.
  function scan(text) {
    let i = 0;
    let rootNode = null;
    const ws = () => { while (i < text.length && /\s/.test(text[i])) i++; };
    const fail = () => { throw new Error("json"); };

    function readString() {
      const start = i;
      i++;
      while (i < text.length && text[i] !== '"') i += text[i] === "\\" ? 2 : 1;
      if (i >= text.length) fail();
      i++;
      try { return JSON.parse(text.slice(start, i)); } catch (e) { return text.slice(start + 1, i - 1); }
    }

    function readValue(node) {
      ws();
      node.start = i;
      const ch = text[i];
      if (ch === "{") {
        node.type = "object";
        node.children = new Map();
        i++;
        ws();
        if (text[i] === "}") { i++; node.end = i; return; }
        for (;;) {
          ws();
          if (text[i] !== '"') fail();
          const keyStart = i;
          const key = readString();
          ws();
          if (text[i] !== ":") fail();
          i++;
          const child = { keyStart };
          node.children.set(key, child);
          readValue(child);
          ws();
          if (text[i] === ",") { i++; continue; }
          if (text[i] === "}") { i++; node.end = i; return; }
          fail();
        }
      }
      if (ch === "[") {
        node.type = "array";
        node.children = new Map();
        i++;
        ws();
        if (text[i] === "]") { i++; node.end = i; return; }
        for (let index = 0; ; index++) {
          const child = {};
          node.children.set(String(index), child);
          readValue(child);
          ws();
          if (text[i] === ",") { i++; continue; }
          if (text[i] === "]") { i++; node.end = i; return; }
          fail();
        }
      }
      node.type = "scalar";
      if (ch === '"') { readString(); node.end = i; return; }
      while (i < text.length && !/[\s,\]}]/.test(text[i])) i++;
      if (i === node.start) fail();
      node.end = i;
    }

    // Le JSON peut être entouré de prose ou de clôtures ``` : on part du premier «{».
    i = Math.max(0, text.indexOf("{"));
    rootNode = {};
    try { readValue(rootNode); } catch (e) { /* arbre partiel */ }
    return rootNode;
  }

  /**
   * Plage [start, end) à sélectionner pour un chemin d'erreur. Un membre absent
   * (champ requis manquant) renvoie la plus proche valeur parente trouvée.
   */
  function pointerRange(text, pointer) {
    let node = scan(text || "");
    if (node.start === undefined) return { start: 0, end: 0, found: false };
    let found = true;
    for (const token of parsePointer(pointer)) {
      const child = node.children && node.children.get(token);
      if (!child || child.start === undefined) { found = false; break; }
      node = child;
    }
    const end = node.end !== undefined ? node.end : node.start;
    if (found) return { start: node.keyStart !== undefined ? node.keyStart : node.start, end, found };
    // Membre absent (champ requis manquant) : juste après l'accolade du parent.
    const inside = Math.min(node.start + 1, end);
    return { start: inside, end: inside, found };
  }

  /** Ligne et colonne (1-indexées, comme le rapport du serveur) → position dans le texte. */
  function lineColumnOffset(text, line, column) {
    let offset = 0;
    for (let current = 1; current < line; current++) {
      const next = text.indexOf("\n", offset);
      if (next === -1) return text.length;
      offset = next + 1;
    }
    return Math.min(text.length, offset + Math.max(0, column - 1));
  }

  /** Clé de tri d'une date du contrat ("-44-03-15", "1971", "present"). */
  function dateKey(value) {
    if (value === "present") return Infinity;
    const match = /^(-?)(\d{1,5})(?:-(\d{2})(?:-(\d{2}))?)?$/.exec(String(value == null ? "" : value).trim());
    if (!match) return NaN;
    const year = Number(match[2]) * (match[1] ? -1 : 1);
    const month = match[3] ? Number(match[3]) : 1;
    const day = match[4] ? Number(match[4]) : 1;
    return year + (month - 1) / 12 + (day - 1) / 372;
  }

  function compareDates(a, b) {
    const ka = dateKey(a), kb = dateKey(b);
    if (Number.isNaN(ka) && Number.isNaN(kb)) return 0;
    if (Number.isNaN(ka)) return 1;
    if (Number.isNaN(kb)) return -1;
    return ka - kb;
  }

  /** Identifiant libre, sur le motif du contrat : « evenement », « evenement-2 »… */
  function uniqueId(doc, base) {
    const used = new Set();
    for (const kind of ["tracks", "eras", "periods", "events"]) {
      for (const item of (doc && doc[kind]) || []) if (item && item.id) used.add(item.id);
    }
    const stem = slug(base) || "element";
    if (!used.has(stem)) return stem;
    for (let n = 2; ; n++) {
      const candidate = `${stem.slice(0, 44)}-${n}`;
      if (!used.has(candidate)) return candidate;
    }
  }

  function slug(text) {
    return String(text || "")
      .normalize("NFKD").replace(/[\u0300-\u036f]/g, "")
      .toLowerCase().replace(/[^a-z0-9]+/g, "_").replace(/^_+|_+$/g, "").slice(0, 40);
  }

  /** Renomme un identifiant partout où il sert de référence (pistes des éléments, liens). */
  function renameId(doc, from, to) {
    if (!doc || from === to) return doc;
    for (const kind of ["periods", "events"]) {
      for (const item of doc[kind] || []) if (item.track === from) item.track = to;
    }
    for (const link of doc.links || []) {
      if (link.from === from) link.from = to;
      if (link.to === from) link.to = to;
    }
    return doc;
  }

  /** Nombre d'éléments qui utilisent une piste. */
  function trackUsage(doc, trackId) {
    let count = 0;
    for (const kind of ["periods", "events"]) {
      for (const item of (doc && doc[kind]) || []) if (item.track === trackId) count++;
    }
    return count;
  }

  /**
   * Paragraphe par paragraphe : le prochain paragraphe à traiter après `currentId`
   * (en bouclant), à faire ou en erreur, de préférence un qui cite des dates.
   */
  function nextPendingChunk(chunks, currentId) {
    const index = chunks.findIndex((c) => c.id === currentId);
    const after = chunks.slice(index + 1).concat(chunks.slice(0, Math.max(0, index)));
    const pending = after.filter((c) => c.status === "pending" || c.status === "error");
    return pending.find((c) => c.mentions > 0) || pending[0] || null;
  }

  /**
   * JSON en cours d'écriture par le modèle local → les éléments datés déjà
   * écrits, [{date, label}], dans l'ordre. Un élément n'y entre qu'avec son
   * libellé complet (guillemet fermant écrit) ; les pistes, sans date, n'y sont pas.
   */
  function partialItems(text) {
    const items = [];
    for (const part of String(text || "").split(/\{\s*"id"\s*:/).slice(1)) {
      const date = /"(?:date|start)"\s*:\s*"([^"]*)"/.exec(part);
      const label = /"label"\s*:\s*"((?:[^"\\]|\\.)*)"/.exec(part);
      if (date && label) items.push({ date: date[1], label: JSON.parse(`"${label[1]}"`) });
    }
    return items;
  }

  /** Texte comparable : sans accents ni casse. */
  function fold(text) {
    return String(text || "").normalize("NFD").replace(/[\u0300-\u036f]/g, "").toLowerCase();
  }

  /**
   * Filtre du rail : l'élément est-il montré ? `filter.hidden` liste les pistes
   * masquées ; chaque mot de `filter.query` doit se trouver dans le libellé, l'id,
   * la date affichée (`dateText`) ou la date telle qu'écrite dans le cours.
   */
  function matchesFilter(item, dateText, filter) {
    if (item.track && filter.hidden.includes(item.track)) return false;
    const words = fold(filter.query).split(/\s+/).filter(Boolean);
    const haystack = fold([item.label, item.id, dateText, item.date_text].join(" "));
    return words.every((word) => haystack.includes(word));
  }

  /** Secondes → « m:ss ». */
  function clock(seconds) {
    const s = Math.max(0, Math.floor(seconds));
    return `${Math.floor(s / 60)}:${String(s % 60).padStart(2, "0")}`;
  }

  return { ORDER, serialize, debounce, singleFlight, parsePointer, elementAt, pointerRange, lineColumnOffset,
           dateKey, compareDates, uniqueId, slug, renameId, trackUsage, nextPendingChunk, partialItems, clock,
           matchesFilter };
});
