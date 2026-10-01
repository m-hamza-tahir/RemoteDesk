[Setup]
AppName=RemoteDesk
AppVersion=1.0.3
DefaultDirName={autopf}\RemoteDesk
DefaultGroupName=RemoteDesk
OutputDir=output
OutputBaseFilename=RemoteDesk-Setup
Compression=lzma
SolidCompression=yes
PrivilegesRequired=admin
CloseApplications=no
RestartApplications=no
Uninstallable=yes

[Files]
Source: "..\dist\RemoteDesk.exe"; DestDir: "{app}"; Flags: ignoreversion

[Icons]
Name: "{group}\RemoteDesk"; Filename: "{app}\RemoteDesk.exe"
Name: "{commondesktop}\RemoteDesk"; Filename: "{app}\RemoteDesk.exe"

[Run]
Filename: "{app}\RemoteDesk.exe"; Description: "Launch RemoteDesk"; Flags: nowait postinstall skipifsilent
