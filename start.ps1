# VanillaEditor 启动脚本
$pythonPath = "$PSScriptRoot\.venv\Scripts\python.exe"
if (-not (Test-Path $pythonPath)) {
    Write-Error "未找到虚拟环境: $pythonPath"
    exit 1
}
Write-Host "启动 VanillaEditor (Python $(& $pythonPath --version 2>&1))" -ForegroundColor Cyan
& $pythonPath "$PSScriptRoot\run.py"