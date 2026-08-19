<#
.SYNOPSIS
  Delete Astra's regenerable build output. Windows counterpart of clean.sh.

.DESCRIPTION
  Everything this removes is produced by run.ps1 / run.sh / tauri build and
  comes back on the next build. Nothing here is tracked by git.

  It never touches data you cannot regenerate:
    astra\astra.db          your opportunities and profile
    astra\applicant.yaml    your applicant details
    .env                    your keys
    astra\.seen_positions.json, astra\reza results\, exported CSV/JSON/HTML

  Default pass frees the big three (PyInstaller build+dist, the Rust target
  directory, the staged sidecars). -All additionally removes node_modules and
  the HTTP cache, which are slower to rebuild but equally regenerable.

.PARAMETER All
  Also remove dashboard\node_modules (npm install to restore) and the HTTP
  conditional-GET cache.

.PARAMETER DryRun
  Print what would be deleted, and how much it would free, without deleting.

.EXAMPLE
  .\scripts\clean.ps1 -DryRun
.EXAMPLE
  .\scripts\clean.ps1 -All
#>
[CmdletBinding()]
param(
    [switch]$All,
    [switch]$DryRun
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

$Repo = Split-Path -Parent $PSScriptRoot

# Regenerable build output. Order is cosmetic (biggest first) so the running
# total looks sensible as it goes.
$targets = @(
    'dashboard\src-tauri\target'            # cargo, the single biggest item
    'dashboard\src-tauri\sidecar\api'       # staged PyInstaller sidecars
    'astra\build'                           # PyInstaller work dir
    'astra\dist'                            # PyInstaller output
    'dashboard\.next'
    'dashboard\out'
    'dashboard\.swc'
    'dashboard\tsconfig.tsbuildinfo'
    'dashboard\src-tauri\gen'               # tauri-generated schemas/icons
)
if ($All) {
    $targets += @(
        'dashboard\node_modules'            # npm install restores it
        'astra\.http_cache.sqlite'          # conditional-GET cache
        'astra\.http_cache.sqlite-journal'
        'astra\.http_cache.sqlite-wal'
        'astra\.http_cache.sqlite-shm'
    )
}

function Get-SizeBytes([string]$Path) {
    # -Force on Get-Item: without it a hidden file (astra\.http_cache.sqlite
    # and friends) is found by Test-Path and then not found by Get-Item.
    if (Test-Path -LiteralPath $Path -PathType Leaf) { return [int64](Get-Item -LiteralPath $Path -Force).Length }
    # `Measure-Object -Sum` emits NOTHING when the pipeline is empty, so the
    # obvious `(... | Measure-Object -Sum).Sum` throws under StrictMode the
    # first time it meets an empty directory — which dashboard\.next usually
    # is. A plain foreach has no such edge, and stays in this scope, unlike a
    # ForEach-Object block where `$sum += ...` would silently accumulate into
    # a copy and always return 0.
    $sum = [int64]0
    foreach ($f in @(Get-ChildItem -LiteralPath $Path -Recurse -File -Force -ErrorAction SilentlyContinue)) {
        $sum += [int64]$f.Length
    }
    return $sum
}
function Format-Size([int64]$b) {
    if ($b -ge 1GB) { return '{0,8:N2} GB' -f ($b / 1GB) }
    if ($b -ge 1MB) { return '{0,8:N1} MB' -f ($b / 1MB) }
    return '{0,8:N0} KB' -f ($b / 1KB)
}

$total = [int64]0
foreach ($rel in $targets) {
    $path = Join-Path $Repo $rel
    if (-not (Test-Path -LiteralPath $path)) { continue }
    $size = Get-SizeBytes $path
    $total += $size
    if ($DryRun) {
        Write-Host ("  would free {0}  {1}" -f (Format-Size $size), $rel)
    } else {
        Write-Host ("  removing     {0}  {1}" -f (Format-Size $size), $rel)
        Remove-Item -LiteralPath $path -Recurse -Force -ErrorAction SilentlyContinue
    }
}

# Python bytecode caches, wherever they landed.
$pycache = @(Get-ChildItem -LiteralPath (Join-Path $Repo 'astra') -Recurse -Directory -Force `
    -Filter '__pycache__' -ErrorAction SilentlyContinue)
foreach ($d in $pycache) {
    $total += Get-SizeBytes $d.FullName
    if (-not $DryRun) { Remove-Item -LiteralPath $d.FullName -Recurse -Force -ErrorAction SilentlyContinue }
}
if ($pycache.Count -gt 0) {
    $verb = if ($DryRun) { 'would remove' } else { 'removed' }
    $noun = if ($pycache.Count -eq 1) { 'directory' } else { 'directories' }
    Write-Host ("  {0} {1} __pycache__ {2}" -f $verb, $pycache.Count, $noun)
}

Write-Host ''
if ($DryRun) {
    Write-Host ("would free {0} in total. Run without -DryRun to do it." -f (Format-Size $total)) -ForegroundColor Cyan
} else {
    Write-Host ("freed {0}. Next build restores everything." -f (Format-Size $total)) -ForegroundColor Green
}
if (-not $All) {
    Write-Host 'Add -All to also drop node_modules and the HTTP cache.' -ForegroundColor DarkGray
}
