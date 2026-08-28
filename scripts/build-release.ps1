[CmdletBinding()]
param(
    [string]$OutputDir
)

$ErrorActionPreference = 'Stop'

$RepoRoot = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
if (-not $OutputDir) {
    $OutputDir = Join-Path $RepoRoot 'dist'
}
$OutputDir = [IO.Path]::GetFullPath($OutputDir)

$PyProject = Join-Path $RepoRoot 'mcp\education-resources\pyproject.toml'
$VersionMatch = Select-String -Path $PyProject -Pattern '^version\s*=\s*"([^"]+)"' | Select-Object -First 1
if (-not $VersionMatch) {
    throw 'Cannot determine release version from mcp/education-resources/pyproject.toml'
}
$Version = $VersionMatch.Matches[0].Groups[1].Value

$StageBase = Join-Path $OutputDir '.release-stage'
$ReleaseName = "LearningResourceFlow-$Version"
$ReleaseRoot = Join-Path $StageBase $ReleaseName
$ZipPath = Join-Path $OutputDir "$ReleaseName-windows.zip"

if (Test-Path $StageBase) { Remove-Item -Recurse -Force $StageBase }
New-Item -ItemType Directory -Force -Path $ReleaseRoot | Out-Null

function Copy-File([string]$Source, [string]$Destination) {
    if (-not (Test-Path $Source -PathType Leaf)) {
        throw "Required release file not found: $Source"
    }
    $parent = Split-Path -Parent $Destination
    if ($parent) { New-Item -ItemType Directory -Force -Path $parent | Out-Null }
    Copy-Item -Force $Source $Destination
}

function Copy-Directory([string]$Source, [string]$Destination) {
    if (-not (Test-Path $Source -PathType Container)) {
        throw "Required release directory not found: $Source"
    }
    $parent = Split-Path -Parent $Destination
    if ($parent) { New-Item -ItemType Directory -Force -Path $parent | Out-Null }
    Copy-Item -Recurse -Force $Source $Destination
}

# End-user entry files.
Copy-File (Join-Path $RepoRoot 'packaging\windows\README.md') (Join-Path $ReleaseRoot 'README.md')
Copy-File (Join-Path $RepoRoot 'packaging\windows\install.cmd') (Join-Path $ReleaseRoot 'install.cmd')
Copy-File (Join-Path $RepoRoot 'packaging\windows\install.ps1') (Join-Path $ReleaseRoot 'install.ps1')

# MCP runtime: source package + its runtime verifier only. No tests, demos, probes or dev README.
$ReleaseMcp = Join-Path $ReleaseRoot 'mcp'
Copy-File $PyProject (Join-Path $ReleaseMcp 'pyproject.toml')
Copy-Directory (Join-Path $RepoRoot 'mcp\education-resources\src') (Join-Path $ReleaseMcp 'src')
Copy-File (
    Join-Path $RepoRoot 'mcp\education-resources\scripts\verify_runtime_environment.py'
) (Join-Path $ReleaseMcp 'scripts\verify_runtime_environment.py')

# Skill runtime: SKILL.md and references are the only runtime inputs. Regression/example suites stay in the dev repo.
$ReleaseSkill = Join-Path $ReleaseRoot 'skill'
Copy-File (Join-Path $RepoRoot 'skills\SKILL.md') (Join-Path $ReleaseSkill 'SKILL.md')
Copy-Directory (Join-Path $RepoRoot 'skills\references') (Join-Path $ReleaseSkill 'references')

# Remove local/generated runtime debris that may exist in a developer checkout.
$JunkDirectoryNames = @(
    '__pycache__',
    '.pytest_cache',
    '.mypy_cache',
    '.ruff_cache',
    'node_modules',
    'tests'
)
Get-ChildItem -Path $ReleaseRoot -Directory -Recurse -Force |
    Sort-Object FullName -Descending |
    Where-Object { $JunkDirectoryNames -contains $_.Name } |
    Remove-Item -Recurse -Force
Get-ChildItem -Path $ReleaseRoot -File -Recurse -Force |
    Where-Object { $_.Extension -in @('.pyc', '.pyo') } |
    Remove-Item -Force

# The CCTV fallback executes a prebuilt main.js/worker.js pair. Release packages
# retain only that runtime bundle and its provenance/license; npm/tsx/TypeScript
# sources and reverse-engineering artifacts stay in the development repository.
$CctvVendor = Join-Path $ReleaseMcp 'src\education_resource_mcp\vendor\cctv-h5e'
foreach ($relative in @(
    'README.md',
    'LICENSE',
    'package.json',
    'package-lock.json',
    'tsconfig.json',
    'src',
    'build'
)) {
    $target = Join-Path $CctvVendor $relative
    if (Test-Path $target) { Remove-Item -Recurse -Force $target }
}
$AllowedCctvRuntimeFiles = @(
    'runtime\LICENSE',
    'runtime\README.md',
    'runtime\main.js',
    'runtime\worker.js'
)
foreach ($file in Get-ChildItem -Path $CctvVendor -File -Recurse -Force) {
    $relative = [IO.Path]::GetRelativePath($CctvVendor, $file.FullName)
    if ($AllowedCctvRuntimeFiles -notcontains $relative) {
        throw "Unexpected CCTV development artifact leaked into release: $relative"
    }
}

# Release is built from an allowlist. This assertion prevents accidental leakage if the builder changes later.
$ForbiddenNames = @(
    'legacy',
    '.agent',
    '.openclaw-test',
    'semantic-regression-cases.json',
    'run_semantic_baseline.py',
    'cctv.worker.orig.js',
    'cctv.worker.diff',
    'AGENTS.md',
    'CONTEXT.md',
    'IDENTITY.md',
    'SOUL.md',
    'TOOLS.md',
    'USER.md'
)
foreach ($item in Get-ChildItem -Path $ReleaseRoot -Recurse -Force) {
    if ($ForbiddenNames -contains $item.Name) {
        throw "Forbidden development artifact leaked into release: $($item.FullName)"
    }
}

if (Test-Path $ZipPath) { Remove-Item -Force $ZipPath }
New-Item -ItemType Directory -Force -Path $OutputDir | Out-Null
Compress-Archive -Path $ReleaseRoot -DestinationPath $ZipPath -CompressionLevel Optimal
Remove-Item -Recurse -Force $StageBase

Write-Host "Release built: $ZipPath" -ForegroundColor Green
Write-Output $ZipPath
