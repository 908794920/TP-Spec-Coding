@echo off
node "%~dp0workbench-manager.mjs" stop
if errorlevel 1 pause
