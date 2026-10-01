# RemoteDesk Client

This repository contains the Windows RemoteDesk client only.

The same client EXE acts as both:
- Agent (shares this PC screen)
- Controller (controls other registered PCs)

The server is NOT included in this repository. The server runs separately on the dedicated server laptop.

## GitHub release

Push a tag such as `v1.0.0` or run the workflow manually. GitHub Actions builds `RemoteDesk.exe` with PyInstaller and attaches it to the GitHub Release.

## Local test

```bat
python -m pip install -r requirements.txt
python client\client.py
```
