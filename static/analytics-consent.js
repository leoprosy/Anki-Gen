/* Mémorise un choix explicite avant toute collecte de statistiques. */
(() => {
  const panel = document.getElementById('analytics-consent');
  if (!panel) return;
  const buttons = [...panel.querySelectorAll('[data-consent]')];
  const error = document.getElementById('analytics-consent-error');

  async function choose(enabled) {
    buttons.forEach((button) => { button.disabled = true; });
    error.hidden = true;
    try {
      const response = await fetch('/api/settings', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ analytics_enabled: enabled, analytics_decided: true }),
      });
      if (!response.ok) throw new Error('save failed');
      panel.remove();
    } catch (_) {
      error.textContent = window.T('js.network_error');
      error.hidden = false;
      buttons.forEach((button) => { button.disabled = false; });
    }
  }

  buttons.forEach((button) => button.addEventListener('click', () =>
    choose(button.dataset.consent === 'true')));
})();
