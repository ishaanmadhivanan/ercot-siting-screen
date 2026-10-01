<#
download_parcels.ps1  --  Phase 4 (land)

Downloads TxGIO StratMap Land Parcels (2025 release) county zips into
data\raw\parcels\. Runs on Windows because the TxGIO download server
blocks cloud and data-centre addresses; a home connection works.

The list of files comes from data\seed\parcel_downloads.csv (built from the
TxGIO API, collection 0fa04328-872e-481c-b453-126a74777593).

Usage, from the repo folder:
  powershell -ExecutionPolicy Bypass -File scripts\download_parcels.ps1 -Fips 48475,48161
  powershell -ExecutionPolicy Bypass -File scripts\download_parcels.ps1 -ErcotOnly

Files already downloaded are skipped, so it is safe to re-run after a failure.
#>
param(
    [string[]]$Fips,
    [switch]$ErcotOnly
)

$ErrorActionPreference = 'Stop'
$ProgressPreference = 'SilentlyContinue'   # the progress bar makes Invoke-WebRequest very slow

$repo = Split-Path -Parent $PSScriptRoot
$list = Import-Csv (Join-Path $repo 'data\seed\parcel_downloads.csv')
$out  = Join-Path $repo 'data\raw\parcels'
New-Item -ItemType Directory -Force -Path $out | Out-Null

if ($ErcotOnly) {
    $ercot = Import-Csv (Join-Path $repo 'data\seed\ercot_counties.csv') | ForEach-Object { $_.county_fips }
    $todo = $list | Where-Object { $ercot -contains $_.county_fips }
} elseif ($Fips) {
    $wanted = $Fips | ForEach-Object { $_ -split ',' } | ForEach-Object { $_.Trim() }
    $todo = $list | Where-Object { $wanted -contains $_.county_fips }
} else {
    Write-Host 'Give -Fips 48475,48161 or -ErcotOnly'
    exit 1
}

$mb = [math]::Round((($todo | Measure-Object -Property filesize_bytes -Sum).Sum) / 1MB)
Write-Host "$($todo.Count) counties, about $mb MB"

$i = 0
foreach ($row in $todo) {
    $i++
    $dest = Join-Path $out ("parcels_{0}.zip" -f $row.county_fips)
    if ((Test-Path $dest) -and ((Get-Item $dest).Length -eq [int64]$row.filesize_bytes)) {
        Write-Host "[$i/$($todo.Count)] $($row.county_name) already downloaded"
        continue
    }
    Write-Host "[$i/$($todo.Count)] $($row.county_name) ($([math]::Round([int64]$row.filesize_bytes / 1MB)) MB)"
    try {
        Invoke-WebRequest -Uri $row.url -OutFile $dest -UseBasicParsing
    } catch {
        Write-Host "   FAILED: $($_.Exception.Message)  (re-run to retry)"
        if (Test-Path $dest) { Remove-Item $dest }
    }
}
Write-Host 'Done.'
