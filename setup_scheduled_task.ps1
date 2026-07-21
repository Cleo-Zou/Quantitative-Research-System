# 创建 Windows 任务计划程序 — 每个交易日下午 17:00 自动更新基金数据
# 右键 → 使用 PowerShell 运行，或在终端执行: powershell -ExecutionPolicy Bypass -File setup_scheduled_task.ps1

$taskName = "IndexFundMonitor"
$scriptPath = "d:\Intern\Index_Enhancement_Monitor\run_scheduled.bat"

# 删除旧任务（如果存在）
schtasks /Delete /TN $taskName /F 2>$null

# 创建新任务
schtasks /Create `
    /TN $taskName `
    /TR $scriptPath `
    /SC WEEKLY `
    /D MON,TUE,WED,THU,FRI `
    /ST 17:00 `
    /F `
    /RL HIGHEST

if ($LASTEXITCODE -eq 0) {
    Write-Host ""
    Write-Host "========================================" -ForegroundColor Green
    Write-Host "  [OK] 任务计划创建成功！" -ForegroundColor Green
    Write-Host "========================================" -ForegroundColor Green
    Write-Host ""
    Write-Host "任务名称: $taskName"
    Write-Host "执行脚本: $scriptPath"
    Write-Host "执行时间: 每个工作日 17:00"
    Write-Host ""
    Write-Host "验证方式: schtasks /Query /TN $taskName"
    Write-Host "手动运行: schtasks /Run /TN $taskName"
    Write-Host ""
} else {
    Write-Host "[FAIL] 创建失败，请尝试以管理员身份运行此脚本" -ForegroundColor Red
}

pause
