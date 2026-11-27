param([string]$Python = 'python')

$ErrorActionPreference = 'Stop'
Push-Location -LiteralPath $PSScriptRoot
try {
    $icon = (Resolve-Path -LiteralPath './app/report.ico').Path
    & $Python -m PyInstaller --noconfirm --onefile --windowed --name SRMReportExporter `
        --icon $icon --add-data ('{0}:.' -f $icon) --collect-data playwright `
        --exclude-module numpy --exclude-module pandas `
        --workpath './build/package' --specpath './build' --distpath './dist' './app/main.py'
    if ($LASTEXITCODE -ne 0) {
        throw "PyInstaller failed with exit code $LASTEXITCODE."
    }
} finally {
    Pop-Location
}
