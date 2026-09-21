@echo off
node "%~dp0workbench-manager.mjs" restart
if errorlevel 1 pause
