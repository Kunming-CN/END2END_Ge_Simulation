# Read-only ES contract adapter. No Julia, output reservation or source edits.
[CmdletBinding()]
param([Parameter(Mandatory=$true)][string]$Profile)
$ErrorActionPreference='Stop'
$root=[IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..'))
. (Join-Path $PSScriptRoot 'electronics_settings.ps1')
$sources=Get-ESSources $root
$selected=Get-ESInput $root $Profile $sources
@{selection=$selected;sources_sha256=$sources}|ConvertTo-Json -Depth 30 -Compress
