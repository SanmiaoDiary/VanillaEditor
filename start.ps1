# VanillaEditor 启动脚本
$projectRoot = $PSScriptRoot
$venvPython = Join-Path $projectRoot ".venv\Scripts\python.exe"

if (Test-Path $venvPython) {
    Write-Host "启动 VanillaEditor (使用 .venv)" -ForegroundColor Cyan
    & $venvPython "$projectRoot\run.py"
} else {
    Write-Host "未找到 .venv，尝试使用系统 python..." -ForegroundColor Yellow
    python "$projectRoot\run.py"
}