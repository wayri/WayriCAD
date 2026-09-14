@echo off
setlocal
python "%~dp0tools\install_suite.py" %*
exit /b %errorlevel%
