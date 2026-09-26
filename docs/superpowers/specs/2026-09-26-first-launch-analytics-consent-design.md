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

The owner additionally chose genuine customization. Keep one-click **Allow all**
and **Decline all** at equal prominence, and add **Customize** as a third action.
It reveals two initially unchecked choices: installation/activity statistics
(`first_launch`, `app_opened`) and creation statistics (`project_created`,
`cards_saved`, `export_completed`). Each category is available in Settings too.
The first-launch event and automatic activity events require activity consent;
product actions require creation consent. Accepting only creation statistics
must not emit installation or activity events. Existing single-switch opt-ins
migrate to both categories. If one category is later disabled, queued events
from that category are removed while the other category remains enabled.
The local random installation ID is shared by permitted events; both choices
explain this and still require a positive action. The panel calls these
"usage statistics", not browser cookies, because the app stores its ID in its
data directory. One-click refusal remains because the
[CNIL guidance](https://www.cnil.fr/fr/questions-reponses-lignes-directrices-modificatives-et-recommandation-cookies-traceurs)
requires refusal to be as easy as acceptance.

Existing false `analytics_enabled` values cannot reliably distinguish an old
explicit refusal from the previous default. Those installations may see the
new prompt once after updating, without sending data before a new Allow.

## Verification

Use Flask tests for no tracking before consent, persistence of both choices,
and compatibility with existing acceptance. Use the packaged executable in
headless Chrome to verify both buttons, French and English text, a narrow
window, failed-save retry, and a stale Settings tab. Disable the production
ingestion token during browser checks.
