[CmdletBinding()]
param(
    [switch]$SkipOpenClawOnboarding
)

$ErrorActionPreference = 'Stop'

function Section([string]$Text) { Write-Host "`n>>> $Text" -ForegroundColor Cyan }
function Ok([string]$Text) { Write-Host "  [OK] $Text" -ForegroundColor Green }
function Warn([string]$Text) { Write-Host "  [WARN] $Text" -ForegroundColor Yellow }
function Fail([string]$Text) { throw $Text }

function Refresh-Path {
    $machine = [Environment]::GetEnvironmentVariable('Path', 'Machine')
    $user = [Environment]::GetEnvironmentVariable('Path', 'User')
    $env:Path = @($machine, $user) -join ';'
}

function Get-WebText([string]$Url) {
    $response = Invoke-WebRequest -UseBasicParsing $Url
    if ($response.Content -is [byte[]]) {
        return [Text.Encoding]::UTF8.GetString([byte[]]$response.Content)
    }
    return [string]$response.Content
}

function Invoke-Native([scriptblock]$Block, [string]$What) {
    $prev = $ErrorActionPreference
    $ErrorActionPreference = 'Continue'
    try {
        & $Block
        $code = $LASTEXITCODE
    }
    finally {
        $ErrorActionPreference = $prev
    }
    if ($code -ne 0) {
        throw "$What failed (exit $code)"
    }
}

function Find-Python312 {
    $candidates = @()

    if (Get-Command py.exe -ErrorAction SilentlyContinue) {
        try {
            $resolved = (& py.exe -3.12 -c "import sys; print(sys.executable)" 2>$null | Select-Object -First 1).Trim()
            if ($resolved) { $candidates += $resolved }
        }
        catch {}
    }

    foreach ($name in @('python.exe', 'python3.exe')) {
        $command = Get-Command $name -ErrorAction SilentlyContinue
        if ($command) { $candidates += $command.Source }
    }

    foreach ($candidate in $candidates | Select-Object -Unique) {
        try {
            & $candidate -c "import sys; raise SystemExit(0 if sys.version_info >= (3, 12) else 1)" 2>$null
            if ($LASTEXITCODE -eq 0) { return $candidate }
        }
        catch {}
    }
    return $null
}

function Ensure-WingetPackage([string]$Id, [string]$DisplayName) {
    if (-not (Get-Command winget.exe -ErrorAction SilentlyContinue)) {
        Fail "$DisplayName is missing and winget is unavailable. Install App Installer/winget, then run install.cmd again."
    }
    Section "Installing $DisplayName"
    Invoke-Native {
        winget.exe install --id $Id -e --silent --accept-package-agreements --accept-source-agreements
    } "Install $DisplayName"
    Refresh-Path
}

$PackageRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$McpSource = Join-Path $PackageRoot 'mcp'
$SkillSource = Join-Path $PackageRoot 'skill'

if (-not (Test-Path (Join-Path $McpSource 'pyproject.toml'))) {
    Fail "Package is incomplete: mcp\pyproject.toml not found. Extract the whole release ZIP before installing."
}
if (-not (Test-Path (Join-Path $SkillSource 'SKILL.md'))) {
    Fail "Package is incomplete: skill\SKILL.md not found. Extract the whole release ZIP before installing."
}

$InstallRoot = Join-Path $env:LOCALAPPDATA 'LearningResourceFlow'
$AppRoot = Join-Path $InstallRoot 'app'
$InstalledMcp = Join-Path $AppRoot 'mcp'
$VenvRoot = Join-Path $InstallRoot 'venv'
$DataRoot = Join-Path $InstallRoot 'data'
$LibraryRoot = Join-Path ([Environment]::GetFolderPath('MyDocuments')) '学习资料库'
$OpenClawWasMissing = $false

Section 'Checking OpenClaw'
if (-not (Get-Command openclaw -ErrorAction SilentlyContinue)) {
    $OpenClawWasMissing = $true
    Write-Host '  OpenClaw is not installed. Installing it first without launching onboarding.'
    $installer = Get-WebText 'https://openclaw.ai/install.ps1'
    & ([scriptblock]::Create($installer)) -NoOnboard
    Refresh-Path
}
if (-not (Get-Command openclaw -ErrorAction SilentlyContinue)) {
    Fail 'OpenClaw installation finished but the openclaw command is still unavailable. Reopen PowerShell and run install.cmd again.'
}
if ($OpenClawWasMissing) {
    Invoke-Native { openclaw setup --baseline } 'Initialize OpenClaw baseline'
}
Ok 'OpenClaw available'

Section 'Checking Python 3.12+'
$Python = Find-Python312
if (-not $Python) {
    Ensure-WingetPackage 'Python.Python.3.12' 'Python 3.12'
    $Python = Find-Python312
}
if (-not $Python) {
    Fail 'Python 3.12+ could not be found after installation.'
}
Ok "Python: $Python"

Section 'Checking ffmpeg'
if (-not (Get-Command ffmpeg.exe -ErrorAction SilentlyContinue)) {
    Ensure-WingetPackage 'Gyan.FFmpeg' 'FFmpeg'
}
if (-not (Get-Command ffmpeg.exe -ErrorAction SilentlyContinue)) {
    Fail 'FFmpeg could not be found after installation.'
}
Ok 'FFmpeg available'

Section 'Installing education-resources MCP'
New-Item -ItemType Directory -Force -Path $InstallRoot, $DataRoot, $LibraryRoot | Out-Null
if (Test-Path $AppRoot) { Remove-Item -Recurse -Force $AppRoot }
New-Item -ItemType Directory -Force -Path $AppRoot | Out-Null
Copy-Item -Recurse -Force $McpSource $InstalledMcp

# Reinstall the runtime itself on upgrades; keep data/jobs/sessions outside the venv.
if (Test-Path $VenvRoot) { Remove-Item -Recurse -Force $VenvRoot }
Invoke-Native { & $Python -m venv $VenvRoot } 'Create Python virtual environment'
$VenvPython = Join-Path $VenvRoot 'Scripts\python.exe'
$McpExe = Join-Path $VenvRoot 'Scripts\education-resource-mcp.exe'

Invoke-Native {
    & $VenvPython -m pip install --disable-pip-version-check --no-input $InstalledMcp
} 'Install education-resource-mcp'

$RuntimeCheck = Join-Path $InstalledMcp 'scripts\verify_runtime_environment.py'
Invoke-Native { & $VenvPython $RuntimeCheck } 'Verify Python runtime'
Ok 'MCP Python runtime installed'

Section 'Checking CCTV compatibility runtime'
if (-not (Get-Command node.exe -ErrorAction SilentlyContinue) -and -not (Get-Command node -ErrorAction SilentlyContinue)) {
    Fail 'Node is unavailable. OpenClaw normally supplies Node; repair OpenClaw and run install.cmd again.'
}
$VendorDir = (& $VenvPython -c "import education_resource_mcp, pathlib; print(pathlib.Path(education_resource_mcp.__file__).resolve().parent / 'vendor' / 'cctv-h5e' / 'runtime')" | Select-Object -First 1).Trim()
if (-not (Test-Path (Join-Path $VendorDir 'main.js')) -or -not (Test-Path (Join-Path $VendorDir 'worker.js'))) {
    Fail "CCTV compatibility runtime is incomplete: $VendorDir"
}
Ok 'CCTV compatibility runtime ready'

Section 'Installing learning-resource-flow Skill'
Invoke-Native {
    openclaw skills install $SkillSource --global --force
} 'Install learning-resource-flow Skill'
Ok 'Skill installed globally'

Section 'Registering MCP in OpenClaw'
$mcpConfig = @{
    command = $McpExe
    args = @()
    env = @{
        EDUCATION_RESOURCE_MCP_DATA_DIR = $DataRoot
        EDUCATION_RESOURCE_MCP_LIBRARY_DIR = $LibraryRoot
    }
} | ConvertTo-Json -Compress
Invoke-Native {
    openclaw mcp set education-resources $mcpConfig
} 'Register education-resources MCP'
Invoke-Native {
    openclaw mcp doctor education-resources --probe
} 'Probe education-resources MCP'
Ok 'OpenClaw can start and inspect education-resources'

if ($OpenClawWasMissing -and -not $SkipOpenClawOnboarding) {
    Section 'OpenClaw first-time setup'
    Write-Host '  The learning-resource package is installed. Complete OpenClaw model/provider setup now.'
    Invoke-Native { openclaw setup --wizard } 'OpenClaw first-time setup'
}

Section 'Applying OpenClaw changes'
$prev = $ErrorActionPreference
$ErrorActionPreference = 'Continue'
try {
    openclaw gateway restart --safe
    $restartCode = $LASTEXITCODE
}
finally {
    $ErrorActionPreference = $prev
}
if ($restartCode -eq 0) {
    Ok 'Gateway restarted'
}
else {
    Warn 'Gateway restart was not available. The MCP and Skill are installed; restart/start your OpenClaw Gateway before the next chat.'
    # Gateway restart is best-effort after a successful MCP probe. Consume its
    # native exit code so a missing Gateway credential does not turn the whole
    # successful installation into a failed process exit.
    $global:LASTEXITCODE = 0
}

Section 'Installation complete'
Write-Host "  Program: $InstallRoot"
Write-Host "  Runtime data: $DataRoot"
Write-Host "  Learning library: $LibraryRoot"
Write-Host ''
if ($SkipOpenClawOnboarding -and $OpenClawWasMissing) {
    Warn 'OpenClaw onboarding was skipped. Run `openclaw setup --wizard` before using the assistant.'
}
else {
    Write-Host 'OpenClaw is ready to use learning-resource-flow in a new chat.' -ForegroundColor Green
}
