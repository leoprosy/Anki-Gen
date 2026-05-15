(() => {
  const prompts = window.PROMPTS || PROMPTS;
  if (!prompts || !prompts.length) return;

  const els = {
    list: document.getElementById("chunk-list"),
    curId: document.getElementById("cur-id"),
    curDeck: document.getElementById("cur-deck"),
    curPrompt: document.getElementById("cur-prompt"),
    response: document.getElementById("response"),
    saveBtn: document.getElementById("save-btn"),
    saveNextBtn: document.getElementById("save-next-btn"),
    saveStatus: document.getElementById("save-status"),
    prevBtn: document.getElementById("prev-btn"),
    nextBtn: document.getElementById("next-btn"),
    progressLabel: document.getElementById("progress-label"),
    progressFill: document.getElementById("progress-fill"),
    cardsInfo: document.getElementById("cards-info"),
    chunkView: document.getElementById("chunk-view"),
  };

  const firstPending = prompts.findIndex(p => p.status !== "done");
  let currentIdx = firstPending >= 0 ? firstPending : 0;

  // ── Chunk transition (cross-fade) ──────────────────────────
  function transitionChunkView(callback) {
    if (!els.chunkView) { callback(); return; }
    els.chunkView.classList.add("switching");
    setTimeout(() => {
      callback();
      els.chunkView.classList.remove("switching");
    }, 150);
  }

  function render() {
    const p = prompts[currentIdx];
    els.curId.textContent = `#${p.id}`;
    els.curDeck.textContent = p.deck;
    els.curPrompt.textContent = p.prompt;
    els.response.value = p.response || "";
    updateCardsInfo();
    els.saveStatus.textContent = "";
    els.saveStatus.className = "muted";

    for (const li of els.list.querySelectorAll(".chunk-item")) {
      const id = parseInt(li.dataset.id, 10);
      li.classList.toggle("active", id === p.id);
    }

    els.prevBtn.disabled = currentIdx === 0;
    els.nextBtn.disabled = currentIdx === prompts.length - 1;

    const activeLi = els.list.querySelector(".chunk-item.active");
    if (activeLi) activeLi.scrollIntoView({ block: "nearest", behavior: "smooth" });
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
    const lines = text.split(/\r?\n/).filter(l => l.trim() && !l.startsWith("```"));
    const cards = lines.filter(l => l.includes("\t") || l.includes(";"));
    els.cardsInfo.textContent = `${cards.length} carte(s) détectée(s)`;
  }

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
  const responseContainer = document.getElementById('response-container');
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
