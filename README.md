# RemoteDesk — Clean Full MVP

## What this package contains

- `server/` — central broker server.
- `client/` — Windows Agent + Controller.
- `installer/` — Windows EXE/installer build.
- `.github/workflows/build.yml` — GitHub Actions builds `RemoteDesk-Setup.exe`.

## Connection model

- One controller can open multiple target sessions.
- One target can have multiple controller sessions.
- Multiple controllers can operate multiple targets simultaneously.
- Every client is both Agent and Controller.
- Installing the client on the server laptop intentionally makes that laptop
  controllable too.

## IMPORTANT NETWORK REQUIREMENT

The central server must be reachable from the Internet on TCP 8765.
If the server is behind a home router, port forwarding may be required.
If the ISP uses CGNAT, normal inbound port forwarding will not work and an
external relay/VPS/Tailscale-style network is required.

## CLEAN INSTALL

### 1. Old setup

Do not mix the old RemoteDesk files with this package. You can leave the old
folder untouched, but stop the old server before starting this one.

### 2. Server laptop

Install Python 3.12+ and run:

    python -m pip install -r requirements.txt
    python tools/make_cert.py
    server\ALLOW_FIREWALL.bat
    python server\server.py --host 0.0.0.0 --port 8765

Keep this window running.

### 3. Client EXE

Do not install Python on friends' PCs. Build the installer through GitHub
Actions or build locally on Windows.

The GitHub Action creates:

    RemoteDesk-Setup.exe

Friends install that file.

### 4. First client launch

Each laptop chooses:
- Device name
- Permanent password

The application generates a unique Device ID.

### 5. Server address

The packaged client currently defaults to:

    182.178.213.210:8765

Change this in `client.py` before building if the server public address changes.

## SECURITY

This is an MVP. Before public production deployment, add:
- certificate verification/pinning
- device revocation
- failed-login rate limiting
- audit logging
- explicit controller authorization
- control arbitration
- direct P2P/NAT traversal
- relay fallback
- low-latency video transport such as WebRTC/H.264
- signed Windows binaries

Never distribute `config/server.key`.

## TEST ORDER

1. Test server + client on the same LAN.
2. Test two laptops.
3. Test one controller with two targets.
4. Test two controllers with one target.
5. Test several controllers/targets.
6. Only then test Internet access.
