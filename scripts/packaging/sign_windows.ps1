# Sign RemoteAble.exe with an Authenticode certificate.
#
# Required environment variables:
#   WINDOWS_SIGNING_CERT_PATH   Path to .pfx file
#   WINDOWS_SIGNING_CERT_PASSWORD
#
# Usage:
#   pwsh scripts/packaging/sign_windows.ps1 dist/RemoteAble/RemoteAble.exe

param(
    [Parameter(Mandatory = $true)]
    [string]$ExePath
)

$ErrorActionPreference = "Stop"

if (-not (Test-Path $ExePath)) {
    throw "Executable not found: $ExePath"
}

$certPath = $env:WINDOWS_SIGNING_CERT_PATH
$certPassword = $env:WINDOWS_SIGNING_CERT_PASSWORD

if (-not $certPath) {
    throw "Set WINDOWS_SIGNING_CERT_PATH to your .pfx certificate file."
}

$securePassword = ConvertTo-SecureString -String $certPassword -AsPlainText -Force
$cert = New-Object System.Security.Cryptography.X509Certificates.X509Certificate2($certPath, $securePassword)

Set-AuthenticodeSignature -FilePath $ExePath -Certificate $cert -TimestampServer "http://timestamp.digicert.com"
Write-Host "Signed $ExePath"
