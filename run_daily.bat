@echo off
cd /d "%~dp0"
echo ============================================================
echo  指数增强基金监控 - 每日自动更新
echo  %date% %time%
echo ============================================================

echo.
echo [1/4] 更新基金池（缓存加速）...
python 01_build_fund_pool1.py
if errorlevel 1 (
    echo [FAIL] 01 失败，跳过后续步骤
    exit /b 1
)

echo.
echo [2/4] 获取最新净值...
python 02_update_nav.py
if errorlevel 1 (
    echo [FAIL] 02 失败，跳过后续步骤
    exit /b 1
)

echo.
echo [3/4] 计算涨跌幅和超额...
python 03_calculate_return.py
if errorlevel 1 (
    echo [FAIL] 03 失败，跳过后续步骤
    exit /b 1
)

echo.
echo [4/6] 生成绩效HTML页面...
python 04_generate_html.py
if errorlevel 1 (
    echo [FAIL] 04 失败
    exit /b 1
)

echo.
echo [5/6] 生成研究分析Excel...
python 05_export_analysis.py
if errorlevel 1 (
    echo [WARN] 05 失败（非致命，继续）
)

echo.
echo [6/6] 生成研究HTML看板...
python 06_generate_research_html.py
if errorlevel 1 (
    echo [WARN] 06 失败（非致命，继续）
)

echo.
echo ============================================================
echo  完成！
echo     output\index.html          绩效看板
echo     output\research.html       研究看板
echo     output\research_analysis.xlsx  研究分析
echo ============================================================
pause
