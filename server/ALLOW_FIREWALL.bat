@echo off
netsh advfirewall firewall add rule name="RemoteDesk FINAL 8765" dir=in action=allow protocol=TCP localport=8765
pause
