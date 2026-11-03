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

$useAzure = $env:AZURE_CLIENT_ID -and $env:AZURE_CLIENT_SECRET -and $env:AZURE_TENANT_ID -and $env:ARTIFACT_SIGNING_ENDPOINT
$useCertificate = $env:WINDOWS_CERTIFICATE -and $env:WINDOWS_CERTIFICATE_PASSWORD
if (-not ($useAzure -or $useCertificate)) { throw "no signing credentials in the environment" }

$pfx = $null
try {
  if ($useAzure) {
    foreach ($item in $items) {
      artifact-signing-cli -e $env:ARTIFACT_SIGNING_ENDPOINT -a $env:ARTIFACT_SIGNING_ACCOUNT -c $env:ARTIFACT_SIGNING_PROFILE -d "formCAD" $item.FullName
      if ($LASTEXITCODE -ne 0) { throw "signing failed for $($item.FullName)" }
    }
  } else {
    $signtool = Find-SignTool
    $pfx = Join-Path ([System.IO.Path]::GetTempPath()) ("formcad-" + [guid]::NewGuid().ToString("N") + ".pfx")
    [System.IO.File]::WriteAllBytes($pfx, [Convert]::FromBase64String($env:WINDOWS_CERTIFICATE))
    foreach ($item in $items) {
      & $signtool sign /f $pfx /p $env:WINDOWS_CERTIFICATE_PASSWORD /fd sha256 /tr $Timestamp /td sha256 $item.FullName
      if ($LASTEXITCODE -ne 0) { throw "signing failed for $($item.FullName)" }
    }
  }
  if (-not $useAzure) {
    foreach ($item in $items) {
      & $signtool verify /pa $item.FullName
      if ($LASTEXITCODE -ne 0) { throw "signature check failed for $($item.FullName)" }
    }
  }
  Write-Host "signed $($items.Count) files under $Path"
}
finally {
  if ($pfx -and (Test-Path $pfx)) { Remove-Item $pfx -Force }
}
