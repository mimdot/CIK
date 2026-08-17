# Changelog

All notable changes to Astra. Format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/); versions follow
[Semantic Versioning](https://semver.org/).

## [1.0.0] — 2026-08-17

First release under the name **Astra**. The desktop app is the headline: it
now starts, renders, and every control in it does what it says.

### Added

- **Astra identity** across all three surfaces — the constellation mark, the
  Archivo type scale and the ground/ink/accent palette, applied to the CLI
  header, the dashboard chrome and the generated HTML report. Fonts are
  self-hosted, so the desktop app renders correctly with no network.
- **`./run.sh`** — one command from the repo root builds whatever is stale and
  launches. Installs a menu entry, so every launch after the first is one
  click. A no-op run takes 0.14s.
- **Saved items** — bookmark opportunities *and* supervisors, in a two-tab
  Saved view with counts, search, sort, a personal note and an
  interested/applied/rejected tag. Entries are kept by a stable key derived
  from the record itself, with a snapshot, so a saved position survives a
  re-crawl and still reads correctly after the source page comes down.
- **Sign-in with an email and a shared access code**, in front of the existing
  account system. `CIK_ACCESS_CODE` controls it; leave it unset on a server and
  the ordinary password form comes back. **The code is not security** — see the
  README.
- **Sign out**, which did not exist anywhere before.
- **Stop a running supervisor search**, with live progress showing which field
  and source is being queried. Stopping keeps everything already found.
- External links now open in the system browser, and CSV/JSON exports write a
  real file through a native save dialog and tell you where it went.

### Fixed

- **The desktop app could not start on any platform.** The shell looked for its
  bundled API in the user's `~/.local/bin` instead of beside the executable —
  and on macOS and Windows that directory does not exist at all.
- **A blank white window.** Building with `cargo build` produces a shell with
  no UI embedded; only the Tauri CLI includes the frontend.
- **389 MB of RAM leaked per launch.** The API sidecar was SIGKILLed on exit,
  so its unpacked files were never cleaned up; on a RAM-backed `/tmp` these
  accumulated until launches failed with a decompression error.
- **A single dropped request ended a running search**, reporting "Cannot reach
  the API server" while the search carried on and finished normally.
- Every external link and both exports were silent no-ops in the desktop app.
- The frontend ignored the port the shell had chosen for the API.

### Changed

- CV reading is **off** behind `CV_PARSING_ENABLED`, and the AI drafting
  assistant is off behind `ASSISTANT_ENABLED`, so no user spends API tokens
  yet. The keyword picker is the supported way to define a research profile.
- Supervisor country filtering accepts case, ISO codes and near-misses
  (`germany`, `DE`, `Germny` all find rows stored as `Germany`).

### Security

- Ships under the MIT licence.
- The shared access code is a soft gate, extractable from the binary, and is
  documented as such. It gates nothing; accounts remain the real boundary.

[1.0.0]: https://github.com/mimdot/CIK/releases/tag/v1.0.0
