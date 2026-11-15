@echo off
title Veritas Battle Recorder
chcp 65001 >nul
cd /d "%~dp0"
echo ======================================================
echo   Veritas 战斗日志独立常驻录制器 (Windows Standalone)
echo   此窗口独立于 IDE 运行，关闭窗口即可停止录制
echo ======================================================
"C:\Users\Administrator\AppData\Local\Programs\Python\Python312\python.exe" -X utf8 record_battle.py
pause
