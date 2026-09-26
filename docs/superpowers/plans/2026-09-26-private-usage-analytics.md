# Private usage analytics implementation plan

**Goal:** Ship consented desktop usage events and a private owner dashboard setup.
**Architecture:** A standard-library telemetry outbox sits behind successful Flask
actions. Build configuration selects the PostHog project; owner scripts manage
dashboard setup and read GitHub download counts outside the desktop app.
**Spec:** [Approved design](../specs/2026-09-26-private-usage-analytics-design.md).

## Global constraints

- Branch: `feat/private-usage-analytics`, based on current `origin/main` (6a8bddf).
- English Conventional Commits; issue #26; no merge or release in this task.
- Python 3.11+, unittest; no added runtime dependencies.
- Off by default; no course content, filenames, project IDs or personal keys.
- All product text in both EN and FR catalogs.
- 500 queued events, seven-day expiry, five-second HTTP timeout.

## Tasks

- [x] 1. Add failing tests for strict consent, minimal payloads, durable retry,
  bounded queues, revoked consent and corrupt/unwritable storage. Implement
  `Telemetry.track(event, **properties)`, `preferences_changed()` and `flush_once()`
  in `telemetry.py`; add `analytics_config.py` and strict settings validation.
  Run `.venv/Scripts/python.exe -m unittest discover -s tests -p test_telemetry.py`.
- [x] 2. Add Flask integration tests using temporary project directories and a
  real generated DOCX. Instrument successful project/card/export actions and
  rendered app pages, excluding update checks. Add bilingual Settings consent
  and privacy text. Run the full Python suite and `node --test tests/test_update_ui.js`.
- [x] 3. Build `scripts/configure_analytics.py`, package config and telemetry in
  PyInstaller and both updater workflows. Add owner dashboard and GitHub download
  scripts with contract tests, plus a setup guide and README/CONTRIBUTING links.
- [x] 4. Review the full diff and failures with a fresh reviewer. Run full tests,
  check packaging, render the changed settings UI if tooling is available, commit,
  open and attach a PR, and report any live-account setup still pending.

## Review focus

Test old settings without consent; Boolean-like strings; telemetry state write
failures after a successful save; network retries after a restart; withdrawal
while a request is pending. Audit every property for accidental document content.

## Execution record

- Initial checkout passed 106 tests. Updated the clean feature branch to the
  current GitHub main before implementation; current-main baseline rerun follows.
- Owner supplied the EU public token. Local generated configuration and both
  GitHub Actions variables are configured. No synthetic production events have
  been sent.
- Current-main baseline: 122 Python and 3 JavaScript tests passed. Added tests
  first, observed missing modules/hooks fail, implemented and passed 147 tests.
- Independent review found a consent-withdrawal dispatch race and an inaccurate
  rolling-24-hour label. Added failing regression tests, then synchronized
  preference changes/dispatch authorization and invalidated revoked snapshots.
  Initially changed charts to UTC calendar periods. The live Ankigen project uses
  Europe/Paris and the scoped key cannot change it, so activity is now recorded
  for each successful page visit or product action and PostHog groups unique
  installations by the project's calendar. Final suite: 150 Python + 3 JS passed.
- PyInstaller build passed. Headless Chrome against the packaged executable with
  isolated APPDATA verified default-off consent, persistence, withdrawal, EN/FR,
  800px layout, packaged EU configuration and no telemetry with config disabled.
- The private dashboard was created in PostHog project 285049, ID 976865, with
  nine insights and public sharing disabled; the owner URL is
  https://eu.posthog.com/project/285049/dashboard/976865. Organization membership
  could not be audited with the scoped API key (HTTP 403). The owner must confirm
  sole membership or restrict project access to ensure only they can see it.
