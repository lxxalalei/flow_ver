# Sync MCP packages and skills from this repo to the local Windows OpenClaw deployment.
#
# Run from Windows (PowerShell or Git Bash):
#   powershell -NoProfile -ExecutionPolicy Bypass -File scripts\sync-to-openclaw.ps1
#
# After sync, restart the OpenClaw gateway and verify:
#   openclaw gateway restart
#   openclaw mcp doctor education-resources --probe
#   openclaw mcp doctor session-manager  --probe
$ErrorActionPreference = 'Stop'

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
$Repo     = 'C:\Users\admin\projects\collector_flow'
$WinLocal = "$env:LOCALAPPDATA\OpenClaw"

$EduPkg = "$WinLocal\packages\education-resources\current"
$EduSrc = "$EduPkg\source"
$EduPy  = "$EduPkg\venv\Scripts\python.exe"

$SesPkg = "$WinLocal\packages\session-manager\current"
$SesSrc = "$SesPkg\source"          # created by this script
$SesPy  = "$SesPkg\venv\Scripts\python.exe"

$LrfSkillTarget = "$WinLocal\packages\learning-resource-flow\current\skill"

# session-login-flow is a junction/symlink - resolve to the real dir.
$SesLoginTarget = "$env:USERPROFILE\.openclaw\skills\session-login-flow"
if ((Get-Item $SesLoginTarget -Force).LinkType) {
    $SesLoginTarget = (Get-Item $SesLoginTarget -Force).Target
}

$ExcludeDirs  = @('__pycache__', '.pytest_cache', 'venv', '.venv', 'build', '.git')
$ExcludeFiles = @('*.pyc', '*.egg-info', 'database.sqlite')

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
function Section([string]$Text) { Write-Host "`n>>> $Text" -ForegroundColor Cyan }
function Ok([string]$Text)      { Write-Host "  [OK] $Text" -ForegroundColor Green }
function Fail([string]$Text)    { Write-Host "  [FAIL] $Text" -ForegroundColor Red; exit 1 }

# Native tools (pip/python/robocopy) legitimately write to stderr; under
# $ErrorActionPreference='Stop' a redirected stderr line would become a
# terminating error. Run them with 'Continue' and judge by $LASTEXITCODE only.
function Invoke-Native([scriptblock]$Block, [string]$What) {
    $prev = $ErrorActionPreference
    $ErrorActionPreference = 'Continue'
    try {
        & $Block 2>&1 | ForEach-Object { "$_" }
    }
    finally { $ErrorActionPreference = $prev }
    if ($LASTEXITCODE -ne 0) { throw "$What failed (exit $LASTEXITCODE)" }
}

# robocopy mirrors like rsync --delete; excluded dirs are also spared on the
# destination (venv survives). Exit codes 0-7 are success, >=8 is failure.
function MirrorDir([string]$Src, [string]$Dst, [string[]]$ExtraExcludes = @()) {
    $xd = $ExcludeDirs + $ExtraExcludes
    $prev = $ErrorActionPreference
    $ErrorActionPreference = 'Continue'
    try { robocopy $Src $Dst /MIR /XD $xd /XF $ExcludeFiles /NFL /NDL /NP | Out-Null }
    finally { $ErrorActionPreference = $prev }
    if ($LASTEXITCODE -ge 8) { throw "robocopy failed (exit $LASTEXITCODE): $Src -> $Dst" }
    $global:LASTEXITCODE = 0
}

function InstallEditable([string]$Python, [string]$Source, [string]$Name) {
    $prev = $ErrorActionPreference
    $ErrorActionPreference = 'Continue'
    try {
        $output = & $Python -m pip install -e $Source --no-input 2>&1 | ForEach-Object { "$_" }
        $code = $LASTEXITCODE
    }
    finally { $ErrorActionPreference = $prev }
    if ($code -ne 0) {
        $output | Write-Host
        throw "pip install -e failed for $Name (exit $code)"
    }
    $output | Select-String 'Successfully|error|ERROR|already satisfied'
}

function CheckExists([string[]]$Paths) {
    foreach ($p in $Paths) {
        if (-not (Test-Path $p)) { Fail "Path not found: $p" }
    }
}

# ---------------------------------------------------------------------------
# Pre-flight
# ---------------------------------------------------------------------------
Section 'Pre-flight checks'
CheckExists @(
    "$Repo\mcp\education-resources\src",
    "$Repo\mcp\session-manager\src",
    "$Repo\skills\learning-resource-flow\SKILL.md",
    $EduPy, $SesPy
)
Ok 'All source and venv paths verified'

# ---------------------------------------------------------------------------
# 1. education-resources MCP
# ---------------------------------------------------------------------------
Section 'Syncing education-resources MCP'
MirrorDir "$Repo\mcp\education-resources" $EduSrc
Ok "Source synced to $EduSrc"

InstallEditable $EduPy $EduSrc 'education-resources'
Ok 'Package reinstalled in venv'

Invoke-Native { & $EduPy -m pip check } 'Dependency consistency check (pip check)'
Ok 'Dependency consistency check passed'

Invoke-Native { & $EduPy "$EduSrc\scripts\verify_runtime_environment.py" } 'Runtime environment verification'
Ok 'Runtime environment verification passed'

# Smoke test - verify new adapters load
Invoke-Native {
    & $EduPy -c @'
from education_resource_mcp.adapters.douyin import DouyinSearchAdapter, sign_a_bogus
from education_resource_mcp.adapters.douyin_download import DouyinDownloader
from education_resource_mcp.adapters.bilibili import BilibiliSearchAdapter
print('  adapters: douyin, douyin_download, bilibili import OK')
'@
} 'Import smoke test'
Ok 'Import smoke test passed'

# ---------------------------------------------------------------------------
# 2. session-manager MCP
# ---------------------------------------------------------------------------
Section 'Syncing session-manager MCP'
New-Item -ItemType Directory -Force -Path $SesSrc | Out-Null
MirrorDir "$Repo\mcp\session-manager" $SesSrc -ExtraExcludes @('distribution')
Ok "Source synced to $SesSrc"

InstallEditable $SesPy $SesSrc 'session-manager'
Ok 'Package reinstalled in venv'

Invoke-Native { & $SesPy -m pip check } 'Dependency consistency check (pip check)'
Ok 'Dependency consistency check passed'

# Smoke test - verify douyin registration
Invoke-Native {
    & $SesPy -c @'
from session_manager.store import _PLATFORM_LIST
ids = [p.platform_id for p in _PLATFORM_LIST]
assert 'douyin' in ids, f'douyin not in {ids}'
print(f'  registered platforms: {ids}')
'@
} 'Import smoke test'
Ok 'Import smoke test passed'

# education-resources reads sessions through the standalone session-manager
# package when EDUCATION_RESOURCE_MCP_SESSION_MANAGER_DATA_DIR is configured;
# keep that dependency in sync in this venv too (a stale copy breaks search
# with "未知平台" for platforms like douyin).
InstallEditable $EduPy $SesSrc 'session-manager (edu venv)'
Invoke-Native {
    & $EduPy -c @'
from session_manager.store import _PLATFORM_LIST
ids = [p.platform_id for p in _PLATFORM_LIST]
assert 'douyin' in ids, f'douyin not in {ids}'
print(f'  edu-venv session_manager platforms: {ids}')
'@
} 'session-manager edu-venv verification'
Ok 'session-manager synced into education-resources venv'

# ---------------------------------------------------------------------------
# 3. Skills
# ---------------------------------------------------------------------------
Section 'Syncing learning-resource-flow skill'
MirrorDir "$Repo\skills\learning-resource-flow" $LrfSkillTarget
Ok "Skill synced to $LrfSkillTarget"

Section 'Syncing session-login-flow skill'
if (Test-Path "$Repo\mcp\session-manager\distribution\skills\session-login-flow") {
    MirrorDir "$Repo\mcp\session-manager\distribution\skills\session-login-flow" $SesLoginTarget
    Ok "Skill synced to $SesLoginTarget"
}
else {
    Write-Host '  (skipped - no session-login-flow in repo distribution)'
}

# ---------------------------------------------------------------------------
# Summary
# ---------------------------------------------------------------------------
Section 'Sync complete'
Write-Host @'

  Next steps (run in a Windows terminal):
    openclaw gateway restart
    openclaw mcp doctor education-resources --probe
    openclaw mcp doctor session-manager  --probe

  Or if OpenClaw is managed as a scheduled task, restart via Task Scheduler.
'@
exit 0
