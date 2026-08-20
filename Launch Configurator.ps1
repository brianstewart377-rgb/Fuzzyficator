$ErrorActionPreference = "Stop"

$repositoryRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$rememberedPathFile = Join-Path $repositoryRoot ".fuzzyficator-python.txt"
$configuratorPath = Join-Path $repositoryRoot "Fuzzyficator_configurator.py"
$pythonPath = $null

if (Test-Path -LiteralPath $rememberedPathFile) {
    $candidate = (Get-Content -LiteralPath $rememberedPathFile -Raw).Trim()
    if ($candidate -and (Test-Path -LiteralPath $candidate -PathType Leaf)) {
        $pythonPath = $candidate
    }
}

if (-not $pythonPath) {
    foreach ($commandName in @("py.exe", "python.exe")) {
        $command = Get-Command $commandName -ErrorAction SilentlyContinue
        if ($command) {
            $pythonPath = $command.Source
            break
        }
    }
}

if (-not $pythonPath) {
    Add-Type -AssemblyName System.Windows.Forms
    $dialog = New-Object System.Windows.Forms.OpenFileDialog
    $dialog.Title = "Select the Python executable used by Fuzzyficator"
    $dialog.Filter = "Python executable (python.exe)|python.exe|All executable files (*.exe)|*.exe"
    $dialog.CheckFileExists = $true
    $dialog.Multiselect = $false
    if ($dialog.ShowDialog() -ne [System.Windows.Forms.DialogResult]::OK) {
        Write-Host "No Python executable selected."
        exit 1
    }
    $pythonPath = $dialog.FileName
    Set-Content -LiteralPath $rememberedPathFile -Value $pythonPath -Encoding UTF8
}

Write-Host "Using Python: $pythonPath"
Write-Host "Using script: $configuratorPath"
& $pythonPath $configuratorPath
exit $LASTEXITCODE
