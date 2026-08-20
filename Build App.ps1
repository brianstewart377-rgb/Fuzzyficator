param(
    [string]$PythonPath
)

$ErrorActionPreference = "Stop"
$repositoryRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$rememberedPathFile = Join-Path $repositoryRoot ".fuzzyficator-python.txt"

if (-not $PythonPath -and (Test-Path -LiteralPath $rememberedPathFile)) {
    $candidate = (Get-Content -LiteralPath $rememberedPathFile -Raw).Trim()
    if ($candidate -and (Test-Path -LiteralPath $candidate -PathType Leaf)) {
        $PythonPath = $candidate
    }
}

if (-not $PythonPath) {
    foreach ($commandName in @("py.exe", "python.exe")) {
        $command = Get-Command $commandName -ErrorAction SilentlyContinue
        if ($command) {
            $PythonPath = $command.Source
            break
        }
    }
}

if (-not $PythonPath) {
    throw "Python was not found. Pass -PythonPath with a full path to python.exe."
}

$virtualEnvironment = Join-Path $repositoryRoot ".build-venv"
$buildPython = Join-Path $virtualEnvironment "Scripts\python.exe"
if (-not (Test-Path -LiteralPath $buildPython)) {
    & $PythonPath -m venv $virtualEnvironment
    if ($LASTEXITCODE -ne 0) {
        throw "Could not create the packaging environment."
    }
}

& $buildPython -c "import importlib.util, sys; sys.exit(0 if importlib.util.find_spec('PyInstaller') else 1)"
if ($LASTEXITCODE -ne 0) {
    & $buildPython -m pip install pyinstaller
    if ($LASTEXITCODE -ne 0) {
        throw "Could not install PyInstaller into the local packaging environment."
    }
}

Push-Location $repositoryRoot
try {
    & $buildPython -m PyInstaller --noconfirm --clean FuzzyficatorApp.spec
    if ($LASTEXITCODE -ne 0) {
        throw "PyInstaller failed to build the application."
    }
}
finally {
    Pop-Location
}

$applicationPath = Join-Path $repositoryRoot "dist\Fuzzyficator.exe"
Write-Host "Built: $applicationPath"
