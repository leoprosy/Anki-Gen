# First-launch analytics choice

Responds to [issue #28](https://github.com/leoprosy/Anki-Gen/issues/28).
The owner chose an explicit Allow/Decline prompt before any collection, after
considering default-on tracking. The [CNIL guidance](https://www.cnil.fr/fr/cookies-et-autres-traceurs/regles/cookies-solutions-pour-les-outils-de-mesure-daudience)
limits consent exemptions to audience-measurement configurations meeting specific
conditions; this PostHog configuration has not been shown to qualify.

## Behavior

On a fresh installation, show a small persistent panel at the bottom right of
normal app pages. It explains the recipient and purpose, links to Privacy in
Settings, and offers equally prominent Allow and Decline buttons. The panel
stays until one choice is saved. Settings has the full privacy controls instead
of an overlay, so its Save button remains usable. All text is available in
English and French.

Store `analytics_decided` separately from `analytics_enabled`. Until Allow,
there is no telemetry state, identifier, queue, or upload. Decline persists and
does not prompt again. Existing true `analytics_enabled` values remain accepted
after an update. A failed save keeps the panel and both choices available for
retry. The Settings checkbox can change a previous choice. Saving unrelated
preferences omits both analytics fields, including from a Settings tab left open
while another window records a choice.

Existing false `analytics_enabled` values cannot reliably distinguish an old
explicit refusal from the previous default. Those installations may see the
new prompt once after updating, without sending data before a new Allow.

## Verification

Use Flask tests for no tracking before consent, persistence of both choices,
and compatibility with existing acceptance. Use the packaged executable in
headless Chrome to verify both buttons, French and English text, a narrow
window, failed-save retry, and a stale Settings tab. Disable the production
ingestion token during browser checks.
