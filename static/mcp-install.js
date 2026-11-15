/* Enregistre Ankigen comme serveur MCP chez Claude : panneau d'accueil et bouton des paramètres. */
(() => {
  async function install() {
    try {
      const data = await (await fetch('/api/mcp', { method: 'POST' })).json();
      if (data.ok) return { ok: true, message: window.T('js.mcp_done') };
      return { ok: false, message: window.T('js.mcp_error', { error: Object.values(data.errors).join(' · ') }) };
    } catch (_) {
      return { ok: false, message: window.T('js.network_error') };
    }
  }

  const panel = document.getElementById('mcp-offer');
  if (panel) {
    const buttons = [...panel.querySelectorAll('button')];
    const error = document.getElementById('mcp-offer-error');
    const busy = (on) => buttons.forEach((b) => { b.disabled = on; });

    document.getElementById('mcp-offer-install').addEventListener('click', async () => {
      busy(true);
      error.hidden = true;
      const result = await install();
      if (result.ok) {
        panel.remove();
        window.toast(result.message, 'ok', 8000);
        return;
      }
      error.textContent = result.message;
      error.hidden = false;
      busy(false);
    });

    document.getElementById('mcp-offer-decline').addEventListener('click', async () => {
      busy(true);
      try {
        await fetch('/api/settings', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ mcp_prompt_dismissed: true }),
        });
      } finally {
        panel.remove();
      }
    });
  }

  const button = document.getElementById('mcp-install-btn');
  if (button) {
    const status = document.getElementById('mcp-status');
    button.addEventListener('click', async () => {
      button.disabled = true;
      status.className = 'settings-feedback';
      status.textContent = '…';
      const result = await install();
      status.textContent = result.message;
      status.className = 'settings-feedback ' + (result.ok ? 'is-success' : 'is-error');
      button.disabled = false;
    });
  }
})();
