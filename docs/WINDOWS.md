# Building and running Astra Desktop on Windows

`run.ps1` is the Windows counterpart of `run.sh`: one command that builds the
PyInstaller API sidecar, builds the dashboard and the Tauri shell, drops a
Start Menu shortcut, and launches the app. Both scripts skip any step whose
output is newer than its sources, so a second run with nothing changed goes
straight to launching.

```powershell
git clone https://github.com/mimdot/CIK.git
cd CIK
.\run.ps1
```

Expect **20–40 minutes** the first time — almost all of it Rust compiling
Tauri's dependency tree. Later runs are seconds.

---

## Prerequisites

Four things, none optional. Install them, then **open a new terminal** so the
PATH changes take effect.

| | Get it | Check |
|---|---|---|
| **Python 3.12+** | [python.org/downloads/windows](https://www.python.org/downloads/windows/) — tick *"Add python.exe to PATH"* | `py -3 -V` |
| **Node.js 20+** | [nodejs.org](https://nodejs.org/) (LTS) | `node -v` |
| **Rust (MSVC)** | [rustup.rs](https://rustup.rs/) — accept the default `x86_64-pc-windows-msvc` | `rustc -V` |
| **MSVC build tools** | [Visual Studio Build Tools](https://visualstudio.microsoft.com/visual-cpp-build-tools/) → *Desktop development with C++* | `cargo` links without error |

**Python 3.12 is a hard floor, not a suggestion.** The engine uses PEP 701
f-strings — quotes reused inside an f-string, as in
`f"Funding: {opp.get('funding_status')}"` — which are a `SyntaxError` on 3.11
and below. `run.ps1` checks the version and refuses rather than letting
PyInstaller fail 200 lines later with something unrecognisable. (Other parts of
this repo still say "Python 3.11+"; for the CLI and the dashboard on an older
tree that was true, but 3.12+ is what today's code needs.)

**WebView2** is what Tauri renders into. Windows 10 and 11 ship it, so there is
normally nothing to do. On a stripped or very old Windows 10 image, install the
[Evergreen Runtime](https://developer.microsoft.com/microsoft-edge/webview2/).

**Rust must be the MSVC toolchain, not GNU.** `rustup default stable-msvc` if
you are unsure. Tauri's Windows dependencies do not build under the GNU
toolchain.

---

## Install the Python dependencies

```powershell
py -3 -m pip install -r astra\requirements-desktop.txt
py -3 -m pip install pyinstaller
```

`requirements-desktop.txt` is the short list — exactly what the bundled app
imports, verified by starting the API against nothing else and watching
`/health` answer. The full `requirements.txt` additionally pulls Playwright,
LiteLLM, pandas, psycopg2, Redis and the RQ worker queue: roughly 400 MB that
either `astra-api.spec` excludes from the bundle or a single-user install never
reaches — and Playwright's browser download is one of the two most common
places a Windows install falls over. Use `requirements.txt` if you are running
a server or contributing to the engine.

---

## Build and run

```powershell
.\run.ps1                # build what is stale, then launch
.\run.ps1 -Rebuild       # force a full rebuild first
.\run.ps1 -NoLaunch      # build + install the shortcut, don't start
```

If PowerShell refuses to run the script at all:

```powershell
powershell -ExecutionPolicy Bypass -File .\run.ps1
```

For a distributable installer (`.msi` / setup `.exe`) rather than a local
build, use the Tauri CLI directly:

```powershell
cd dashboard
npx tauri build
```

---

## What is Windows-specific in the build

Three places in the source know they are on Windows. Worth knowing about if a
build behaves oddly.

**The sidecar filename.** Tauri looks up an `externalBin` by host target
triple, so on Windows the file must be
`dashboard\src-tauri\sidecar\api\astra-api-x86_64-pc-windows-msvc.exe`.
`run.ps1` reads the triple from `rustc -vV` and copies it there — the same
thing `run.sh` does with its own triple. A build that reports a missing
external binary is almost always this file under the wrong name.

**No `strip`, no UPX** (`astra/astra-api.spec`). Windows has no `strip`, and
PyInstaller prints an "ignored" line per collected binary if you ask for it —
hundreds of lines that read like errors. UPX is worse than useless here: it
rewrites the PE headers of `python3xx.dll` and `VCRUNTIME140.dll`, which turns
a working bundle into a `0xC0000005` at startup, and a packed PE is one of the
strongest "this is malware" heuristics Defender has. Both are on for
Linux/macOS and off for Windows.

**Killing the sidecar's whole process tree** (`dashboard/src-tauri/src/lib.rs`).
A PyInstaller onefile is *two* processes on Windows: the bootloader unpacks the
bundle into `%TEMP%\_MEIxxxxxx` and then runs the real application as its own
child. Rust's `Child` refers to the bootloader, and `Child::kill()` is
`TerminateProcess` — so killing it leaves the actual backend running. Not a
theoretical risk: an orphan left this way was still answering `/health` an hour
later, still holding port 8000 and the database. Astra therefore puts the
sidecar in a **job object** with `JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE`.
Processes started by a job member join the job automatically, and Windows
terminates every member when the last handle closes — which the kernel does for
us even if Astra is force-quit.

**Temp-directory cleanup** (same file). The bootloader removes its `_MEI`
directory on a clean shutdown, and Windows has no SIGTERM to ask for one, so
the directory is left behind on every exit. Astra sweeps `%TEMP%` at startup:
for each `_MEI*` directory it tries a rename first, and deletes only the ones
that rename successfully. Windows refuses to rename a directory with open
handles beneath it, so that rename is a free lock test, and a second Astra
window (or any other PyInstaller app on the machine) is never touched. This
only works because of the job object above — while orphaned backends survived,
they held their directories open and the sweep correctly skipped every one.

---

## Troubleshooting

**"Windows protected your PC" / SmartScreen.** The app is not code-signed.
*More info → Run anyway*. Same for a locally built `.exe`.

**Defender eats the sidecar mid-build.** A 160 MB freshly written `.exe` that
unpacks itself is the shape of a dropper, and real-time protection sometimes
quarantines `astra\dist\astra-api.exe` before PyInstaller finishes. Add the
repo folder to *Windows Security → Virus & threat protection → Exclusions*, or
build somewhere already excluded.

**`error: linker 'link.exe' not found`.** The MSVC build tools are missing —
install *Desktop development with C++* and open a new terminal.

**`unrecognized subcommand '=true'`.** An old checkout. `VAR=value cmd` is
POSIX shell syntax and is not a way to set an environment variable in
`cmd.exe`; `tauri.conf.json` now uses `npx cross-env TAURI=true npm run build`.
Pull latest.

**The window opens but says the backend could not be started.** The real reason
is in the sidecar's own log:

```powershell
notepad $env:APPDATA\com.astra.app\api.log
```

**A blank white window.** Something ran `cargo build` instead of the Tauri CLI,
so the frontend was never exported into the binary. `.\run.ps1 -Rebuild`.

**`'cross-env' is not recognized as an internal or external command`** — or the
same for `next`, `jest` or `tauri`. The package is installed and its entry
point still will not run. This means `dashboard\node_modules` was installed on
a DIFFERENT operating system and copied here. Cloning the repo does not do
this; copying a whole working folder off a Linux or Mac machine does.

npm records the executables in `node_modules\.bin` as symlinks on Linux and
macOS, and as `.cmd`/`.ps1` shims on Windows. Carried across, every symlink
arrives as a **zero-byte file** with no shim beside it, and the
platform-specific binaries (`@next/swc-*`, `@tauri-apps/cli-*`) are the wrong
OS besides. One line tells you — a healthy Windows install has dozens:

```powershell
(Get-ChildItem dashboard\node_modules\.bin | Where-Object Extension -in '.cmd','.ps1').Count
```

If that prints `0`, reinstall from the lockfile:

```powershell
cd dashboard
npm ci
```

`run.ps1` and `run.sh` both detect this themselves now — they probe for the
shim rather than merely the directory — so a plain `.\run.ps1` repairs it
without being asked.

**Path-length errors deep inside `node_modules` or `target`.** Enable long
paths once, as Administrator:

```powershell
New-ItemProperty -Path 'HKLM:\SYSTEM\CurrentControlSet\Control\FileSystem' `
  -Name LongPathsEnabled -Value 1 -PropertyType DWORD -Force
```

---

## Reclaiming disk space

A full build leaves several gigabytes of regenerable output — the Rust `target`
directory alone is over a gigabyte, and each staged sidecar is 150–350 MB.

```powershell
.\scripts\clean.ps1 -DryRun    # what it would free, deletes nothing
.\scripts\clean.ps1            # the big three: target, build+dist, sidecars
.\scripts\clean.ps1 -All       # also node_modules and the HTTP cache
```

It never touches `astra\astra.db`, `astra\applicant.yaml`, `.env`, your
exported results, or anything else you cannot regenerate. `scripts/clean.sh` is
the same tool for Linux and macOS.
