# Data-only bridge to the existing electronics validation authority. No simulation.
$ErrorActionPreference='Stop'
$workflowRoot=[IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..'))
. (Join-Path $PSScriptRoot 'electronics_settings.ps1')
try {
  $settingsText=[Console]::In.ReadToEnd()
  Invoke-ElectronicsSettings -Root $workflowRoot -Mode check -View advanced -SetJson $settingsText -AsJson
} catch { Write-Error $_ -ErrorAction Continue; exit 2 }
