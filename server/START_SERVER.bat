@echo off
cd /d "%~dp0.."
python -m pip install -r requirements.txt
if not exist config\server.crt (
  echo Creating TLS certificate...
  powershell -ExecutionPolicy Bypass -File tools\make_cert.ps1
)
python server\server.py --host 0.0.0.0 --port 8765
pause
