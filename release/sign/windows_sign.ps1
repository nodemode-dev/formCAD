param(
  [Parameter(Mandatory = $true)][string]$Path,
  [string]$Timestamp = "http://timestamp.digicert.com"
)

$ErrorActionPreference = "Stop"

function Find-SignTool {
  $found = Get-Command signtool.exe -ErrorAction SilentlyContinue
  if ($found) { return $found.Source }
  $kits = Get-ChildItem "${env:ProgramFiles(x86)}\Windows Kits\10\bin" -Recurse -Filter signtool.exe -ErrorAction SilentlyContinue |
    Where-Object { $_.FullName -like "*\x64\*" } | Sort-Object FullName -Descending
  if ($kits) { return $kits[0].FullName }
  throw "signtool.exe was not found"
}

$items = if (Test-Path $Path -PathType Container) {
  Get-ChildItem $Path -Recurse -File | Where-Object { $_.Extension -in ".exe", ".dll", ".pyd", ".msi", ".sys" }
} else {
  Get-Item $Path
}
if (-not $items) { throw "nothing to sign under $Path" }

if (-not ($env:WINDOWS_CERTIFICATE -and $env:WINDOWS_CERTIFICATE_PASSWORD)) { throw "WINDOWS_CERTIFICATE and WINDOWS_CERTIFICATE_PASSWORD are not in the environment" }

$pfx = $null
try {
  $signtool = Find-SignTool
  $pfx = Join-Path ([System.IO.Path]::GetTempPath()) ("formcad-" + [guid]::NewGuid().ToString("N") + ".pfx")
  [System.IO.File]::WriteAllBytes($pfx, [Convert]::FromBase64String($env:WINDOWS_CERTIFICATE))
  foreach ($item in $items) {
    & $signtool sign /f $pfx /p $env:WINDOWS_CERTIFICATE_PASSWORD /fd sha256 /tr $Timestamp /td sha256 $item.FullName
    if ($LASTEXITCODE -ne 0) { throw "signing failed for $($item.FullName)" }
  }
  foreach ($item in $items) {
    & $signtool verify /pa $item.FullName
    if ($LASTEXITCODE -ne 0) { throw "signature check failed for $($item.FullName)" }
  }
  Write-Host "signed $($items.Count) files under $Path"
}
finally {
  if ($pfx -and (Test-Path $pfx)) { Remove-Item $pfx -Force }
}
