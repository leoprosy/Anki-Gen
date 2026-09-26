/* Mémorise un choix explicite avant toute collecte de statistiques. */
(() => {
  const panel = document.getElementById('analytics-consent');
  if (!panel) return;
  const buttons = [...panel.querySelectorAll('button')];
  const error = document.getElementById('analytics-consent-error');
  const customize = document.getElementById('analytics-customize');
  const options = document.getElementById('analytics-options');

  async function choose(usage, product) {
    buttons.forEach((button) => { button.disabled = true; });
    error.hidden = true;
    try {
      const response = await fetch('/api/settings', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ analytics_usage_enabled: usage,
          analytics_product_enabled: product, analytics_decided: true }),
      });
      if (!response.ok) throw new Error('save failed');
      panel.remove();
    } catch (_) {
      error.textContent = window.T('js.network_error');
      error.hidden = false;
      buttons.forEach((button) => { button.disabled = false; });
    }
  }

  panel.querySelectorAll('[data-consent]').forEach((button) => button.addEventListener('click', () => {
    const enabled = button.dataset.consent === 'true';
    choose(enabled, enabled);
  }));
  customize.addEventListener('click', () => {
    options.hidden = !options.hidden;
    customize.setAttribute('aria-expanded', String(!options.hidden));
  });
  document.getElementById('analytics-save-choices').addEventListener('click', () =>
    choose(document.getElementById('consent-usage').checked,
      document.getElementById('consent-product').checked));
})();
