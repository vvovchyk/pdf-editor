@echo off
cd /d "%~dp0"

echo Starting PDF Cleaner...
echo Working directory: %cd%

set FLASK_ENV=development
set FLASK_DEBUG=1

python app.py

pause