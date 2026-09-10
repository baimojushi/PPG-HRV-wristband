@echo off
chcp 65001 >nul
rem ============================================================
rem  PPG/HRV 实时分析系统 - 桌面 UI 一键启动
rem  v0.4.0 research prototype + one-hour experience
rem  位置: D:\项目\交互艺术\冥想室\代码\hrv-monitoring-wristband\PPG_HRV_System_v0.4.0\PPG-HRV-wristband-v0.4.0-refined
rem ============================================================

set "PROJECT_DIR=D:\项目\交互艺术\冥想室\代码\hrv-monitoring-wristband\PPG_HRV_System_v0.4.0\PPG-HRV-wristband-v0.4.0-refined"
set "PYTHON_EXE=C:\Program Files\Python312\python.exe"

if not exist "%PROJECT_DIR%\desktop\run_ui.py" (
    echo [错误] 找不到项目目录: %PROJECT_DIR%
    echo 请确认路径是否正确。
    pause
    exit /b 1
)

if not exist "%PYTHON_EXE%" (
    echo [错误] 找不到 Python: %PYTHON_EXE%
    pause
    exit /b 1
)

echo ============================================================
echo  启动 PPG/HRV 实时分析系统 v0.4.0
echo  目录: %PROJECT_DIR%
echo ============================================================

rem 用 start /B 让 Python 完全脱离 BAT 进程
start "" /B cmd.exe /c ""%PYTHON_EXE%" "%PROJECT_DIR%\desktop\run_ui.py""

exit /b 0