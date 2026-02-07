@echo off
cd /d %~dp0
call venv\Scripts\activate
venv\Scripts\python.exe maintenance.py
pause