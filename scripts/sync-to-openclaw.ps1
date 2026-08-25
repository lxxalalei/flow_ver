# Sync MCP packages and skills from this repo to the local Windows OpenClaw deployment.
#
# Run from Windows (PowerShell or Git Bash):
#   powershell -NoProfile -ExecutionPolicy Bypass -File scripts\sync-to-openclaw.ps1
#
# After sync, restart the OpenClaw gateway and verify:
#   openclaw gateway restart
#   openclaw mcp doctor education-resources --probe
#
# Session capabilities converged into education-resources (eba4578): the
# standalone session-manager MCP, session_bridge.py and the session-login-flow
# skill are retired. Detected leftovers are reported with cleanup commands
# instead of being synced.
$ErrorActionPreference = 'Stop'

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
$Repo     = 'C:\Users\admin\projects\collector_flow'
$WinLocal = "$env:LOCALAPPDATA\OpenClaw"

$EduPkg = "$WinLocal\packages\education-resources\current"
$EduSrc = "$EduPkg\source"
$EduPy  = "$EduPkg\venv\Scripts\python.exe"

$LrfSkillTarget = "$WinLocal\packages\learning-resource-flow\current\skill"

# Retired in eba4578 - only checked so their cleanup is not forgotten.
$OpenClawConfig   = "$env:USERPROFILE\.openclaw\openclaw.json"
$RetiredPkgDir    = "$WinLocal\packages\session-manager"
$RetiredDataDir   = "$WinLocal\session-manager"
$RetiredSkillLink = "$env:USERPROFILE\.openclaw\skills\session-login-flow"

$ExcludeDirs  = @('__pycache__', '.pytest_cache', 'venv', '.venv', 'build', '.git', 'node_modules')
$ExcludeFiles = @('*.pyc', '*.egg-info', 'database.sqlite')

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
function Section([string]$Text) { Write-Host "`n>>> $Text" -ForegroundColor Cyan }
function Ok([string]$Text)      { Write-Host "  [OK] $Text" -ForegroundColor Green }
function Fail([string]$Text)    { Write-Host "  [FAIL] $Text" -ForegroundColor Red; exit 1 }
function Warn([string]$Text)    { Write-Host "  [WARN] $Text" -ForegroundColor Yellow }

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

# Uninstall a package that may already be gone; "not installed" is success too.
function UninstallIfPresent([string]$Python, [string]$Name) {
    $prev = $ErrorActionPreference
    $ErrorActionPreference = 'Continue'
    try {
        $output = & $Python -m pip uninstall -y $Name --no-input 2>&1 | ForEach-Object { "$_" }
        $code = $LASTEXITCODE
    }
    finally { $ErrorActionPreference = $prev }
    $global:LASTEXITCODE = 0
    if ($output | Select-String 'Successfully uninstalled') {
        Ok "Removed stale $Name from venv"
    }
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
    "$Repo\skills\SKILL.md",
    $EduPy
)
Ok 'All source and venv paths verified'

# ---------------------------------------------------------------------------
# 1. education-resources MCP
# ---------------------------------------------------------------------------
Section 'Syncing education-resources MCP'
MirrorDir "$Repo\mcp\education-resources" $EduSrc
Ok "Source synced to $EduSrc"

# The converged package absorbed session-manager; drop any stale editable
# install left over from the standalone deployment (its source path is gone).
UninstallIfPresent $EduPy 'openclaw-session-manager'

InstallEditable $EduPy $EduSrc 'education-resources'
Ok 'Package reinstalled in venv'

Invoke-Native { & $EduPy -m pip check } 'Dependency consistency check (pip check)'
Ok 'Dependency consistency check passed'

Invoke-Native { & $EduPy "$EduSrc\scripts\verify_runtime_environment.py" } 'Runtime environment verification'
Ok 'Runtime environment verification passed'

# Smoke test - verify adapters and the converged session store load
Invoke-Native {
    & $EduPy -c @'
from education_resource_mcp.adapters.douyin import DouyinSearchAdapter, sign_a_bogus
from education_resource_mcp.adapters.douyin_download import DouyinDownloader
from education_resource_mcp.adapters.bilibili import BilibiliSearchAdapter
from education_resource_mcp.sessions import SessionStore
print('  adapters: douyin, douyin_download, bilibili + SessionStore import OK')
'@
} 'Import smoke test'
Ok 'Import smoke test passed'

# ---------------------------------------------------------------------------
# 2. Skills
# ---------------------------------------------------------------------------
Section 'Syncing learning-resource-flow skill'
MirrorDir "$Repo\skills" $LrfSkillTarget
Ok "Skill synced to $LrfSkillTarget"

# ---------------------------------------------------------------------------
# 3. Retired session-manager leftovers
# ---------------------------------------------------------------------------
Section 'Checking retired session-manager leftovers'
$leftovers = $false
if ((Test-Path $OpenClawConfig) -and
    (Select-String -Path $OpenClawConfig -Pattern 'session-manager' -SimpleMatch -Quiet)) {
    $leftovers = $true
    Warn "openclaw.json still references session-manager - remove the 'session-manager' MCP entry"
    Warn "  and the EDUCATION_RESOURCE_MCP_SESSION_MANAGER_DATA_DIR env var, then restart the gateway"
}
if (Test-Path $RetiredPkgDir) {
    $leftovers = $true
    Warn "Retired package still deployed: $RetiredPkgDir"
    Warn "  after openclaw.json is cleaned: Remove-Item -Recurse -Force `"$RetiredPkgDir`""
}
if (Test-Path $RetiredSkillLink) {
    $leftovers = $true
    Warn "Retired session-login-flow skill still installed: $RetiredSkillLink"
    Warn "  login guidance now comes from resource_session_status; remove it or the gateway"
    Warn "  keeps exposing the obsolete skill"
}
if (Test-Path $RetiredDataDir) {
    $leftovers = $true
    Warn "Old session data dir kept (old encrypted logins are NOT readable by the new store):"
    Warn "  $RetiredDataDir - logins must be re-captured; archive or delete at will"
}
if (-not $leftovers) { Ok 'No session-manager leftovers detected' }

# ---------------------------------------------------------------------------
# Summary
# ---------------------------------------------------------------------------
Section 'Sync complete'
Write-Host @'

  Next steps (run in a Windows terminal):
    openclaw gateway restart
    openclaw mcp doctor education-resources --probe

  Or if OpenClaw is managed as a scheduled task, restart via Task Scheduler.
'@
exit 0
