@echo off
cd /d "%~dp0"
set LOG_DIR=data\log
if not exist "%LOG_DIR%" mkdir "%LOG_DIR%"

set LOG_FILE=%LOG_DIR%\scheduled_update_%date:~0,4%%date:~5,2%%date:~8,2%.log

echo ============================================================  >> "%LOG_FILE%"
echo  指数增强基金监控 - 自动更新                                           >> "%LOG_FILE%"
echo  %date% %time%                                                      >> "%LOG_FILE%"
echo ============================================================         >> "%LOG_FILE%"

echo [1/4] 更新基金池... >> "%LOG_FILE%"
python 01_build_fund_pool1.py >> "%LOG_FILE%" 2>&1
if errorlevel 1 (
    echo [FAIL] 01 失败 >> "%LOG_FILE%"
    exit /b 1
)

echo [2/4] 获取最新净值... >> "%LOG_FILE%"
python 02_update_nav.py >> "%LOG_FILE%" 2>&1
if errorlevel 1 (
    echo [FAIL] 02 失败 >> "%LOG_FILE%"
    exit /b 1
)

echo [3/4] 计算涨跌幅和超额... >> "%LOG_FILE%"
python 03_calculate_return.py >> "%LOG_FILE%" 2>&1
if errorlevel 1 (
    echo [FAIL] 03 失败 >> "%LOG_FILE%"
    exit /b 1
)

echo [4/6] 生成HTML页面... >> "%LOG_FILE%"
python 04_generate_html.py >> "%LOG_FILE%" 2>&1
if errorlevel 1 (
    echo [FAIL] 04 失败 >> "%LOG_FILE%"
    exit /b 1
)

echo [5/6] 研究分析Excel... >> "%LOG_FILE%"
python 05_export_analysis.py >> "%LOG_FILE%" 2>&1
if errorlevel 1 (
    echo [WARN] 05 失败 >> "%LOG_FILE%"
)

echo [6/6] 研究HTML看板... >> "%LOG_FILE%"
python 06_generate_research_html.py >> "%LOG_FILE%" 2>&1
if errorlevel 1 (
    echo [WARN] 06 失败 >> "%LOG_FILE%"
)

echo [OK] 完成 %date% %time% >> "%LOG_FILE%"
exit /b 0
