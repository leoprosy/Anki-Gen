# Private usage analytics

Responds to [issue #26](https://github.com/leoprosy/Anki-Gen/issues/26).
The owner approved PostHog and instructed implementation in this conversation.

## Outcome

Measure observed installations, active installations, projects, card saves and
successful exports in a private PostHog dashboard. Downloads remain a separate
GitHub metric. No accounts are required for Ankigen users.

## Collection and consent

`analytics_enabled` is strictly boolean and false by default. The bilingual
Settings page explains the fields and recipient before the user enables it.
No identifier, queue or network request is created before consent. Missing
configuration and development runs also disable collection (an explicit developer
environment switch allows testing against a separate project).

Only allowlisted event fields leave the device: counts, TSV/ZIP format, app
version, OS family, schema version, time and random installation/event IDs.
Never send project IDs (currently derived from filenames), course titles, paths,
documents, questions, answers, prompts, raw errors or clipboard contents.
Disable person-profile processing and GeoIP enrichment. No browser autocapture
or session replay. The provider still receives the connection's IP address.

Disabling analytics clears pending events. Keep the random installation ID and
first-observation marker locally to avoid counting consent toggles as installs.
An already in-flight request can finish; no later request may start while disabled.
Previously delivered events remain subject to the owner's PostHog retention policy.

## Events and definitions

| Event | Trigger / properties |
| --- | --- |
| `first_launch` | First consented observation; stable event ID, once per installation data directory. Label as first observed installations, including upgrades. |
| `app_opened` | Each successful page visit or product action, with a timestamp so the project's timezone defines the reporting day. No background update polling. Unique installation IDs provide observed DAU/WAU/MAU. |
| `project_created` | Successful parse and project save; `chunk_count`. |
| `cards_saved` | Successful changed response save; `card_count`. Repeated identical saves emit no event. This measures saves, not unique lifetime cards. |
| `export_completed` | TSV or ZIP assembled and response prepared; `card_count`, `format`. Repeated exports are distinct actions. Does not prove filesystem delivery or Anki import. |

Do not backfill old projects. Counts cover participating installations and may
undercount offline clients or overcount a copied/reset data directory. Public
ingestion tokens cannot establish tamper-proof or billable usage.

## Transport and packaging

Use Python's standard library to keep compatibility with the repository's small
dependency set. Persist a bounded JSON outbox atomically under DATA_DIR, outside
the updatable app directory. Maximum 500 queued events and seven days retention;
drop the oldest events beyond these limits. Upload batches in a daemon thread,
with a five-second network timeout and retry delay. Keep original timestamps and
UUIDs on retries. Disk/config/network failures never fail a user action.

Ship only the public project token and EU/US region in `analytics_config.json`.
Generate it from build environment variables in PyInstaller and both GitHub
release paths. Accept only official EU/US ingestion hosts. Personal/read/admin
API keys never belong in the distributed bundle.

## Owner dashboard

Provide an owner-only setup script using a personal API key supplied locally via
environment or hidden input. Create a non-public dashboard with observed installs,
DAU/WAU/MAU, projects, saved-card volume, exports, exported-card volume and app
versions. Verify public sharing is disabled. Keep the PostHog organization limited
to the owner and enable MFA; never turn on public links or embeds.

Provide a separate read-only script for GitHub release asset download counts,
classifying .exe/.msi installers separately from app.zip updater downloads.
Explain that rebuilt/deleted release assets lose their historical counters.

## Verification

Use unittest with real temporary files and Flask's test client. Mock only the
network boundary and background scheduling. Prove consent gating and withdrawal,
strict payload filtering, persistence across restart, stable retry IDs, queue
bounds, successful-action hooks, no duplicate identical saves, correct export
row counts and failure isolation. Exercise the dashboard setup against a fake
API contract; perform live PostHog verification only with owner-provided access.
