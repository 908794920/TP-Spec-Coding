@echo off
node "%~dp0workbench-manager.mjs" start
if errorlevel 1 pause
