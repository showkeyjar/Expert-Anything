@echo off
chcp 65001 >nul
title ExpertAnything - 电力交易领域演示

echo.
echo ==========================================
echo   ExpertAnything 电力交易领域演示系统
echo ==========================================
echo.
echo 即将启动桌面应用，演示场景：
echo   - 市场架构可视化
echo   - 电价形成机制
echo   - 日前市场交易流程
echo   - LMP节点边际电价
echo.

REM 切换到项目目录
cd /d "%~dp0"

REM 设置环境变量
set PYTHONIOENCODING=utf-8
set QT_QPA_PLATFORM=windows

REM 启动应用
python main.py

if errorlevel 1 (
    echo.
    echo 错误：应用启动失败，请检查 Python 环境
    echo 尝试运行：pip install -r requirements.txt
    pause
)
