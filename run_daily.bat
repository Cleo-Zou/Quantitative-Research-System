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
echo [4/4] 生成HTML页面...
python 04_generate_html.py
if errorlevel 1 (
    echo [FAIL] 04 失败
    exit /b 1
)

echo.
echo ============================================================
echo  完成！打开 output\index.html 查看最新排名
echo ============================================================
pause
