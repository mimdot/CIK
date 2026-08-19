<#
.SYNOPSIS
  Astra - one command to build and run the desktop app on Windows.

.DESCRIPTION
  The Windows counterpart of run.sh. Same shape, same two build steps, same
  staleness rules: the PyInstaller API sidecar, then the app itself, each
  skipped when its output is newer than its sources. A second run with nothing
  changed goes straight to launching.

  It also drops a Start Menu shortcut, which is the "one click": after the
  first run, "Astra" is in the Start Menu and starts the built binary
  directly, with no build step in the way.

  For a distributable installer (.msi / .exe setup) use the packaging path
  instead:  cd dashboard ; npx tauri build

.PARAMETER Rebuild
  Force everything to be rebuilt first.

.PARAMETER NoLaunch
  Build and install the shortcut, but do not start the app.

.EXAMPLE
  .\run.ps1
.EXAMPLE
  .\run.ps1 -Rebuild
#>
[CmdletBinding()]
param(
    [switch]$Rebuild,
    [switch]$NoLaunch
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

# Every external command below (python, npx, rustc) has its exit code checked
# by hand, with a message that says what to do about it. In PowerShell 7.3+
# $PSNativeCommandUseErrorActionPreference can turn a non-zero exit into a
# thrown error before those checks run, replacing "PyInstaller is missing,
# here is the pip line" with a stack trace. Opt out where the setting exists;
# on Windows PowerShell 5.1 it simply does not.
if (Test-Path Variable:PSNativeCommandUseErrorActionPreference) {
    $PSNativeCommandUseErrorActionPreference = $false
}

$Repo   = $PSScriptRoot
$Engine = Join-Path $Repo   'astra'
$Dash   = Join-Path $Repo   'dashboard'
$Tauri  = Join-Path $Dash   'src-tauri'
$App    = Join-Path $Tauri  'target\release\app.exe'

function Say([string]$m) { Write-Host "== $m ==" -ForegroundColor Cyan }
function Die([string]$m) { Write-Host "FAIL: $m" -ForegroundColor Red; exit 1 }

function Need([string]$cmd, [string]$hint) {
    if (-not (Get-Command $cmd -ErrorAction SilentlyContinue)) { Die "'$cmd' is not installed - $hint" }
}

# True when $Target is missing, or any file under $Sources is newer than it.
# Build caches are pruned: they churn on every run and would otherwise report
# everything as permanently stale.
function Test-Stale {
    param([string]$Target, [string[]]$Sources)
    if (-not (Test-Path -LiteralPath $Target)) { return $true }
    $stamp = (Get-Item -LiteralPath $Target -Force).LastWriteTimeUtc
    $prune = '[\\/](__pycache__|node_modules|\.next|target|\.pytest_cache)([\\/]|$)'
    foreach ($s in $Sources) {
        if (-not (Test-Path -LiteralPath $s)) { continue }
        if (Test-Path -LiteralPath $s -PathType Leaf) {
            if ((Get-Item -LiteralPath $s -Force).LastWriteTimeUtc -gt $stamp) { return $true }
            continue
        }
        $hit = Get-ChildItem -LiteralPath $s -Recurse -File -Force -ErrorAction SilentlyContinue |
               Where-Object { $_.FullName -notmatch $prune -and $_.LastWriteTimeUtc -gt $stamp } |
               Select-Object -First 1
        if ($hit) { return $true }
    }
    return $false
}

# --- prerequisites ------------------------------------------------------------
Need rustc 'install Rust from https://rustup.rs (choose the MSVC toolchain)'
Need cargo 'install Rust from https://rustup.rs'
Need npm   'install Node.js 20+ from https://nodejs.org'

# The MSVC linker. Rust on Windows compiles happily without it and then dies at
# the LAST step of a 20-minute build with `error: linker 'link.exe' not found`,
# which is a miserable way to discover a missing prerequisite. Check it up
# front, where the message can say what to install.
#
# Two ways it can legitimately be present: on PATH (a vcvars shell, or a
# portable/extracted toolchain), or registered by the Visual Studio installer,
# which is how rustc finds it on a normal machine. Either is fine.
function Test-MsvcLinker {
    if (Get-Command link.exe -ErrorAction SilentlyContinue) { return $true }
    $vswhere = Join-Path ${env:ProgramFiles(x86)} 'Microsoft Visual Studio\Installer\vswhere.exe'
    if (Test-Path -LiteralPath $vswhere) {
        $found = & $vswhere -products * -latest -requires Microsoft.VisualStudio.Component.VC.Tools.x86.x64 `
                            -property installationPath 2>$null
        if ($found) { return $true }
    }
    return $false
}
if (-not (Test-MsvcLinker)) {
    Die @"
the MSVC linker (link.exe) was not found, so Rust cannot link a Windows binary.

Install "Desktop development with C++" from the Visual Studio Build Tools:
    https://visualstudio.microsoft.com/visual-cpp-build-tools/

then open a NEW terminal. If you already have it, run this from a
"Developer PowerShell for VS" instead, which puts link.exe on PATH.
"@
}

# Python: prefer the `py` launcher pinned to a version, then a bare python.exe.
# Note the shape of $candidates: an explicit exe + args pair, never a single
# string that gets .Split(' ') later. In PowerShell `$parts[1..($n-1)]` with
# $n = 1 is the range 1..0, which counts DOWN and returns element 0 - so
# "python" would have been invoked as `python python -c ...`. Storing the
# arguments separately makes that impossible rather than merely fixed.
$PyExe = $null; $PyArgs = @(); $PyVersion = $null
$candidates = @(
    @{ Exe = 'py';      Args = @('-3.13') },
    @{ Exe = 'py';      Args = @('-3.12') },
    @{ Exe = 'py';      Args = @('-3')    },
    @{ Exe = 'python';  Args = @()        },
    @{ Exe = 'python3'; Args = @()        }
)
foreach ($cand in $candidates) {
    $cmd = Get-Command $cand.Exe -ErrorAction SilentlyContinue
    if (-not $cmd) { continue }
    # The Microsoft Store stub named "python" opens the Store instead of
    # running anything, and reports success while doing it.
    if ($cmd.Source -and $cmd.Source -like '*WindowsApps*') { continue }
    # `--version`, NOT `-c 'print("...")'`.
    #
    # Windows PowerShell 5.1 does not escape embedded double quotes when it
    # hands an argument to a native executable, so the quotes are silently
    # stripped on the way through and Python receives
    #     import sys;print(%d.%d%sys.version_info[:2])
    # which is a SyntaxError. The probe therefore failed for EVERY candidate
    # and the script reported "no usable Python found" on a machine with a
    # perfectly good interpreter on PATH. `--version` needs no quoting at all,
    # so there is nothing left to mis-escape.
    $out = $null
    try {
        $out = & $cand.Exe @($cand.Args) --version 2>&1
    } catch { continue }
    if ($LASTEXITCODE -ne 0 -or -not $out) { continue }
    $text = ($out | Out-String)
    if ($text -notmatch 'Python\s+(\d+)\.(\d+)') { continue }
    $v = "$($Matches[1]).$($Matches[2])"
    if ([int]$Matches[1] -eq 3 -and [int]$Matches[2] -ge 12) {
        $PyExe = $cand.Exe; $PyArgs = $cand.Args; $PyVersion = $v; break
    }
    Write-Host "  (skipping $($cand.Exe) $($cand.Args -join ' ') - Python $v, need 3.12+)" -ForegroundColor DarkGray
}
if (-not $PyExe) {
    Die @"
no usable Python found. Astra needs Python 3.12 or newer - the code uses
PEP 701 f-strings (quotes reused inside an f-string), which are a
SyntaxError on 3.11 and below.

Install it from https://www.python.org/downloads/windows/ and tick
"Add python.exe to PATH" in the installer.
"@
}
$PyLabel = (@($PyExe) + $PyArgs) -join ' '
Say "using Python $PyVersion ($PyLabel)"

# Tauri names external binaries with the host target triple; the bundler strips
# the suffix when it copies them next to the app.
$hostLine = & rustc -vV | Select-String '^host:' | Select-Object -First 1
if (-not $hostLine) { Die "could not read the host target triple from ``rustc -vV``" }
$Triple  = $hostLine.ToString().Split(' ')[1].Trim()
$Sidecar = Join-Path $Tauri "sidecar\api\astra-api-$Triple.exe"
Say "host target triple: $Triple"

# --- 1. the FastAPI sidecar ---------------------------------------------------
$engineSrc = @(
    (Join-Path $Engine 'api'),         (Join-Path $Engine 'core'),
    (Join-Path $Engine 'sources'),     (Join-Path $Engine 'db'),
    (Join-Path $Engine 'matching'),    (Join-Path $Engine 'pipeline'),
    (Join-Path $Engine 'supervisors'), (Join-Path $Engine 'cli'),
    (Join-Path $Engine 'toolkit'),     (Join-Path $Engine 'fields'),
    (Join-Path $Engine 'astra.py'),    (Join-Path $Engine 'astra-api.spec')
)
if ($Rebuild -or (Test-Stale -Target $Sidecar -Sources $engineSrc)) {
    Say 'building the API sidecar (PyInstaller - several minutes)'

    & $PyExe @PyArgs -c 'import PyInstaller' 2>$null
    if ($LASTEXITCODE -ne 0) {
        Die @"
PyInstaller is missing. From this directory:

    $PyLabel -m pip install -r astra\requirements-desktop.txt
    $PyLabel -m pip install pyinstaller

requirements-desktop.txt is the short list - the full requirements.txt pulls
in Playwright, LiteLLM and pandas, ~400 MB the desktop bundle then discards.
"@
    }

    Push-Location $Engine
    try {
        & $PyExe @PyArgs -m PyInstaller --noconfirm astra-api.spec
        if ($LASTEXITCODE -ne 0) { Die 'PyInstaller failed - see the output above' }
    } finally { Pop-Location }

    $built = Join-Path $Engine 'dist\astra-api.exe'
    if (-not (Test-Path -LiteralPath $built)) { Die "PyInstaller produced no $built" }
    New-Item -ItemType Directory -Force -Path (Split-Path $Sidecar) | Out-Null
    Copy-Item -LiteralPath $built -Destination $Sidecar -Force
} else {
    Say 'API sidecar up to date'
}

# --- 2. the app: dashboard export + Tauri shell -------------------------------
# `Test-Path node_modules` on its own is not the question worth asking. A tree
# installed on ANOTHER OS and copied here — which is exactly how this repo
# travelled from Linux — passes that check and then fails on the first tool it
# runs.
#
# npm records .bin entries as SYMLINKS on Linux and as .cmd/.ps1 shims on
# Windows. Copy the Linux tree onto Windows and every symlink lands as a
# zero-byte file with no shim beside it: all 41 of them here. The result is
# `'cross-env' is not recognized as an internal or external command` from
# tauri.conf.json's beforeBuildCommand, which reads like a missing install and
# is not one — the package is right there, only its entry point is unusable.
# The platform-specific optional binaries (@next/swc-*, the Tauri CLI) are the
# wrong architecture for the same reason.
#
# So probe the shim that actually has to work, and rebuild from the lockfile
# when it does not.
# Nested Join-Path, not `Join-Path a b c`: the multi-segment form needs
# -AdditionalChildPath, which is PowerShell 6+. On Windows PowerShell 5.1 —
# what `powershell.exe` still is, and what most users have — it fails with
# "A positional parameter cannot be found that accepts argument '.bin'".
$NodeShim = Join-Path (Join-Path (Join-Path $Dash 'node_modules') '.bin') 'next.cmd'
if (-not (Test-Path -LiteralPath $NodeShim)) {
    if (Test-Path -LiteralPath (Join-Path $Dash 'node_modules')) {
        Say 'dashboard dependencies were installed for another platform - reinstalling'
        Remove-Item -LiteralPath (Join-Path $Dash 'node_modules') -Recurse -Force -ErrorAction SilentlyContinue
    } else {
        Say 'installing dashboard dependencies'
    }
    Push-Location $Dash
    try {
        # `npm ci` when there is a lockfile: it is exact, it starts from a
        # clean tree, and it is what CI runs. `npm install` only as a fallback.
        if (Test-Path -LiteralPath (Join-Path $Dash 'package-lock.json')) { & npm ci }
        else { & npm install }
        if ($LASTEXITCODE -ne 0) { Die 'installing dashboard dependencies failed' }
    } finally { Pop-Location }
}

# Build through the Tauri CLI, never plain `cargo build --release`.
#
# `cargo build` produces a binary that launches, opens its window, starts the
# sidecar - and renders NOTHING. A pure white screen: the frontend is not in
# it. Only the CLI runs the beforeBuildCommand and hands the asset embedding
# the export it expects.
#
# Two staleness questions, not one. A bare `cargo build` refreshes the binary
# WITHOUT rebuilding the frontend, so the shell can be newer than every source
# file while the UI inside it is old. `out/index.html` is the frontend's own
# output, so checking it against the frontend sources catches exactly that.
$frontendSrc = @(
    (Join-Path $Dash 'app'),   (Join-Path $Dash 'components'), (Join-Path $Dash 'lib'),
    (Join-Path $Dash 'hooks'), (Join-Path $Dash 'types'),
    (Join-Path $Dash 'package.json'), (Join-Path $Dash 'next.config.ts')
)
$shellSrc = @(
    (Join-Path $Tauri 'src'), (Join-Path $Tauri 'Cargo.toml'),
    (Join-Path $Tauri 'tauri.conf.json'), (Join-Path $Tauri 'capabilities')
) + $frontendSrc

if ($Rebuild -or
    (Test-Stale -Target $App -Sources $shellSrc) -or
    (Test-Stale -Target (Join-Path $Dash 'out\index.html') -Sources $frontendSrc)) {
    Say 'building the app (dashboard + desktop shell)'
    Push-Location $Dash
    try {
        $env:TAURI = 'true'
        & npx tauri build --no-bundle
        if ($LASTEXITCODE -ne 0) { Die 'tauri build failed - see the output above' }
    } finally {
        Remove-Item Env:\TAURI -ErrorAction SilentlyContinue
        Pop-Location
    }
    # `--no-bundle` stops before the installer step, so nothing has copied the
    # sidecar next to the binary yet. The shell looks for it beside its own
    # executable (lib.rs sidecar_path), so put it there.
    Copy-Item -LiteralPath $Sidecar -Destination (Join-Path $Tauri 'target\release\astra-api.exe') -Force
} else {
    Say 'app up to date'
}

# --- 3. the Start Menu entry (the "one click") --------------------------------
# Best-effort throughout: a missing shortcut is a cosmetic loss, and it must
# never be the reason a successful build reports failure.
if (-not $env:APPDATA) {
    Write-Host '  (no %APPDATA% — skipping the Start Menu shortcut)' -ForegroundColor DarkGray
} else {
    try {
        $startMenu = Join-Path $env:APPDATA 'Microsoft\Windows\Start Menu\Programs'
        New-Item -ItemType Directory -Force -Path $startMenu | Out-Null
        $lnk = Join-Path $startMenu 'Astra.lnk'
        $wsh = New-Object -ComObject WScript.Shell
        $sc  = $wsh.CreateShortcut($lnk)
        $sc.TargetPath       = $App
        $sc.WorkingDirectory = Split-Path $App
        $sc.Description      = 'Astra - your academic constellation'
        $ico = Join-Path $Tauri 'icons\icon.ico'
        if (Test-Path -LiteralPath $ico) { $sc.IconLocation = $ico }
        $sc.Save()
        Say "Start Menu entry installed: $lnk"
    } catch {
        Write-Host "  (could not create the Start Menu shortcut: $($_.Exception.Message))" -ForegroundColor DarkGray
    }
}

if ($NoLaunch) { exit 0 }

# The shell kills the sidecar when its window closes, but that handler never
# runs if the shell is signalled instead (Ctrl-C in this terminal), which would
# leave the API orphaned on the port. Clean up after ourselves either way.
Say 'starting Astra'
try {
    $proc = Start-Process -FilePath $App -PassThru
    # Poll rather than $proc.WaitForExit(). WaitForExit() is a blocking .NET
    # call, and PowerShell cannot interrupt one — Ctrl-C would be swallowed
    # until Astra closed on its own, so the cleanup below (the entire point of
    # this try/finally) would never run when it is most needed.
    while (-not $proc.HasExited) { Start-Sleep -Milliseconds 250 }
} finally {
    Get-CimInstance Win32_Process -Filter "Name = 'astra-api.exe'" -ErrorAction SilentlyContinue |
        Where-Object { $_.ExecutablePath -and $_.ExecutablePath.StartsWith($Tauri, 'OrdinalIgnoreCase') } |
        ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }
}
