$ErrorActionPreference = "Stop"
New-Item -ItemType Directory -Force -Path "config" | Out-Null
$cert = New-SelfSignedCertificate -DnsName "RemoteDeskServer" -CertStoreLocation "Cert:\CurrentUser\My" -NotAfter (Get-Date).AddYears(5)
$pwd = ConvertTo-SecureString -String "RemoteDeskTemp" -Force -AsPlainText
Export-PfxCertificate -Cert $cert -FilePath "config\server.pfx" -Password $pwd | Out-Null
Write-Host "Created config\server.pfx"
Write-Host "For the Python server, run tools\make_cert.py after installing cryptography."
