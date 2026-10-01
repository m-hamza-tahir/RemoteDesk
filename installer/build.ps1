$ErrorActionPreference="Stop"
python -m pip install --upgrade pip
python -m pip install -r requirements.txt pyinstaller
pyinstaller --noconfirm --clean --onefile --windowed --name RemoteDesk client\client.py
Write-Host "Built dist\RemoteDesk.exe"
