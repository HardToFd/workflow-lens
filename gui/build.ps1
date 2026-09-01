param(
    [string]$Python = "python",
    [string]$Workspace = ""
)

$ErrorActionPreference = "Stop"
$templateRoot = Split-Path -Parent $PSScriptRoot
$workspaceRoot = if ($Workspace) { (Resolve-Path -LiteralPath $Workspace).Path } else { $templateRoot }
if (-not (Test-Path -LiteralPath (Join-Path $workspaceRoot "AGENTS.md")) -or
    -not (Test-Path -LiteralPath (Join-Path $workspaceRoot "prds"))) {
    throw "Workspace must contain AGENTS.md and prds/: $workspaceRoot"
}

$distPath = Join-Path $workspaceRoot "dist"
$tempPath = Join-Path ([IO.Path]::GetTempPath()) ("workflow-desk-build-" + [guid]::NewGuid().ToString("N"))
New-Item -ItemType Directory -Path $tempPath | Out-Null
try {
    & $Python -m PyInstaller --noconfirm --clean --onefile --windowed `
        --name WorkflowDesk `
        --distpath $distPath `
        --workpath (Join-Path $tempPath "work") `
        --specpath $tempPath `
        --paths $PSScriptRoot `
        --paths $templateRoot `
        --add-data ((Join-Path $templateRoot "workflow\manifest.json") + ";workflow") `
        (Join-Path $PSScriptRoot "desktop.py")
    if ($LASTEXITCODE -ne 0) {
        throw "PyInstaller failed with exit code $LASTEXITCODE"
    }
} finally {
    Remove-Item -LiteralPath $tempPath -Recurse -Force -ErrorAction SilentlyContinue
}

Write-Output ("Built: " + (Join-Path $distPath "WorkflowDesk.exe"))
