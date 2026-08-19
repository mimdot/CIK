# Changelog

All notable changes to Astra. Format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/); versions follow
[Semantic Versioning](https://semver.org/).

## [1.0.1] — 2026-08-19

**Astra Desktop now actually runs on Windows.** 1.0.0 published Windows
installers built by CI from source that had never been executed on Windows, and
the first real build and launch found five faults — one of which costs people
their accounts on upgrade, on every platform, and one of which left a server
process running after every single exit.

Nothing here changes what Astra does. If you are on Linux or macOS the only
change that reaches you is the database one, and it matters: upgrade to this
before opening an older database.

### Fixed

- **On Windows, closing Astra did not stop its backend.** A PyInstaller onefile
  is two processes: the bootloader unpacks the bundle and runs the real
  application as a child. `Child::kill()` is `TerminateProcess`, which ends only
  the bootloader — so every exit left the backend alive, still answering
  `/health`, still holding port 8000, the SQLite database and 389 MB of
  extracted files. The next launch found 8000 busy, chose a random port, and
  added another one. It also quietly defeated the `%TEMP%` sweep added in 1.0.0,
  which by design refuses to delete a directory any process still has open — and
  one always did. The sidecar is now confined to a **job object** with
  `KILL_ON_JOB_CLOSE`, so Windows collects the whole tree, including when Astra
  is force-quit rather than closed. (Linux was never affected: it gets SIGTERM,
  and the bootloader forwards it.)
- **Upgrading an older install could no longer log you in.** The desktop app
  never runs Alembic, so `db.init.reconcile_columns` is what carries an
  existing database across a schema change — and it refused to add any NOT NULL
  column. `users.role` is NOT NULL, so a database created before that column
  stayed one column short for ever, and every sign-in failed with
  `no such column: users.role` while the reason sat in a log nobody reads. It
  now backfills such a column from the model's own default, and still reports
  (rather than invents) a column with no default to fill it with. **Not
  Windows-specific — this affected every long-lived install.**
- **`'cross-env' is not recognized as an internal or external command`** on
  Windows, with the package plainly installed. A `node_modules` tree installed
  on Linux and copied to Windows arrives with every `.bin` entry a zero-byte
  file — npm writes symlinks there on Unix and `.cmd` shims on Windows — and
  with the wrong-OS `@next/swc` and Tauri CLI binaries. `run.ps1` and `run.sh`
  now probe for the shim instead of merely the directory, and rebuild from the
  lockfile when it is missing.
- **`run.ps1` could never find Python**, and so refused to build on any machine
  at all. It probed each interpreter with
  `-c 'import sys;print("%d.%d"%sys.version_info[:2])'`, and Windows PowerShell
  5.1 does not escape embedded double quotes when passing an argument to a
  native executable — Python received `print(%d.%d%sys.version_info[:2])` and
  raised a `SyntaxError`, for every candidate, so the script reported "no usable
  Python found" with a working 3.14 first on PATH. It now asks `--version`,
  which needs no quoting and has nothing to mis-escape.
- **The API reported version `0.1.0`** from `/health` and in its OpenAPI docs,
  in every build ever shipped. The desktop shell has always passed the real
  version in `ASTRA_VERSION`; `api/app.py` hardcoded a string and ignored it.
  That is the one number a bug report is built on.
- **`run.ps1` now checks for the MSVC linker up front**, instead of letting a
  twenty-minute build end in `error: linker 'link.exe' not found`.
- **Eight tests passed and then errored in teardown on Windows**, with
  `PermissionError: [WinError 32]`. Leaked SQLAlchemy engines and a
  `monkeypatch.chdir` into a temporary directory are both invisible on Linux,
  where an open file can still be unlinked; Windows removes neither. Closed
  centrally in `tests/conftest.py`.
- Two tests asserted platform-specific things that were never true on Windows:
  a path rebuilt with `os.path.join` when the code preserves the separator it
  was given, and a `read_text()` with no encoding, which is cp1252 there and
  fails on the first em dash.

### Changed

- The release workflow installs `requirements-desktop.txt`, not
  `requirements.txt`. The full manifest downloads roughly 400 MB that
  `astra-api.spec` then excludes from the bundle anyway, and Playwright and
  psycopg2 are the two likeliest places the Windows job falls over. Verified:
  the frozen binary starts and `/health` answers with exactly the short list.
- `.gitattributes` pins `*.sh` to LF, so a contributor whose `core.autocrlf` is
  off cannot commit a CRLF shebang and leave Linux reporting
  `/usr/bin/env: 'bash\r': No such file or directory`.
- `.gitignore` ignores the whole sidecar directory rather than a list of target
  triples. Each staged binary is 150–350 MB, well over GitHub's 100 MB limit,
  and a pattern list only has to miss one new triple.
- Removed the dead `cik-api-wrapper.sh`. `lib.rs` has spawned the sidecar
  itself since before the rename, and says so in a comment.
- `docs/WINDOWS.md` documents the cross-platform `node_modules` trap, and the
  README no longer claims Windows is untested — while being explicit that what
  was tested is a from-source build, not the published installer.

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
  account system. `ASTRA_ACCESS_CODE` controls it; leave it unset on a server and
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

[1.0.1]: https://github.com/mimdot/CIK/releases/tag/v1.0.1
[1.0.0]: https://github.com/mimdot/CIK/releases/tag/v1.0.0
