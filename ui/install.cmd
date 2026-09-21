@echo off
node "%~dp0workbench-install.mjs" %*
if errorlevel 1 pause
