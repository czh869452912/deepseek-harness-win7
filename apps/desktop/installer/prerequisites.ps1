# Keep this entry compatible with the PowerShell 2.0 installed by Windows 7 SP1.
param(
  [ValidateSet('standard','aio')][string]$Edition = 'standard',
  [string]$Payload,
  [string]$LogPath,
  [switch]$LibraryOnly
)
$ErrorActionPreference = 'Stop'

function Write-SetupLog([string]$Text) {
  $line = [DateTime]::UtcNow.ToString('o') + ' ' + $Text
  Write-Host $line
  if ($LogPath) { [IO.File]::AppendAllText($LogPath, $line + [Environment]::NewLine, [Text.Encoding]::UTF8) }
}

function Get-RegistryValue([string]$Path, [string]$Name) {
  $key = [Microsoft.Win32.Registry]::LocalMachine.OpenSubKey($Path)
  if (!$key) { return $null }
  try { return $key.GetValue($Name, $null) } finally { $key.Close() }
}

function Test-ServicingPackage([string]$KB) {
  $key = [Microsoft.Win32.Registry]::LocalMachine.OpenSubKey('SOFTWARE\Microsoft\Windows\CurrentVersion\Component Based Servicing\Packages')
  if (!$key) { return $false }
  try {
    foreach ($name in $key.GetSubKeyNames()) {
      if ($name -like ('Package_for_' + $KB + '~*')) {
        $package = $key.OpenSubKey($name)
        try { if ($package.GetValue('CurrentState', 0) -eq 112) { return $true } } finally { $package.Close() }
      }
    }
  } finally { $key.Close() }
  return $false
}

function Test-RebootPending {
  foreach ($path in @('SOFTWARE\Microsoft\Windows\CurrentVersion\Component Based Servicing\RebootPending',
                     'SOFTWARE\Microsoft\Windows\CurrentVersion\WindowsUpdate\Auto Update\RebootRequired')) {
    $key = [Microsoft.Win32.Registry]::LocalMachine.OpenSubKey($path)
    if ($key) { $key.Close(); return $true }
  }
  return $false
}

function Get-PrerequisiteState {
  $version = [Environment]::OSVersion.Version
  $win7 = $version.Major -eq 6 -and $version.Minor -eq 1
  $net = Get-RegistryValue 'SOFTWARE\Microsoft\NET Framework Setup\NDP\v4\Full' 'Release'
  $ps = Get-RegistryValue 'SOFTWARE\Microsoft\PowerShell\3\PowerShellEngine' 'PowerShellVersion'
  if (!$ps) { $ps = '2.0' }
  return @{
    Win7 = $win7
    Net = $net -and [int]$net -ge 461808
    PowerShell = [Version]$ps -ge [Version]'5.1'
    WMF3 = [Version]$ps -ge [Version]'3.0' -and [Version]$ps -lt [Version]'4.0'
    SSU = !$win7 -or (Test-ServicingPackage 'KB4490628')
    SHA2 = !$win7 -or (Test-ServicingPackage 'KB4474419')
    D3D = !$win7 -or [IO.File]::Exists([IO.Path]::Combine($env:WINDIR, 'System32\D3DCompiler_47.dll'))
  }
}

function Invoke-OfflineInstaller([string]$Name, [string]$Arguments) {
  $file = [IO.Path]::Combine($Payload, $Name)
  if (![IO.File]::Exists($file)) { throw ('Missing offline payload: ' + $Name) }
  if ($Name.EndsWith('.msu')) {
    $executable = [IO.Path]::Combine($env:WINDIR, 'System32\wusa.exe')
    $Arguments = '"' + $file + '" /quiet /norestart'
  } else { $executable = $file }
  Write-SetupLog ('Installing ' + $Name)
  # PS2 Start-Process -PassThru can lose the exit handle after WaitForExit,
  # yielding null (then 0) for failed installers and required restarts.
  $info = New-Object Diagnostics.ProcessStartInfo
  $info.FileName = $executable
  $info.Arguments = $Arguments
  $info.UseShellExecute = $false
  $info.CreateNoWindow = $true
  $process = New-Object Diagnostics.Process
  $process.StartInfo = $info
  try {
    [void]$process.Start()
    if (!$process.WaitForExit(1800000)) {
      try { $process.Kill() } catch { }
      throw ('Offline installer exceeded 30 minute deadline: ' + $Name)
    }
    $code = [BitConverter]::ToUInt32([BitConverter]::GetBytes([int]$process.ExitCode), 0)
    Write-SetupLog ($Name + ' exit=' + $code)
    return $code
  } finally { $process.Close() }
}

function Invoke-Prerequisites([string]$SelectedEdition, [string]$Architecture) {
  $state = Get-PrerequisiteState
  $missing = @('SSU','SHA2','D3D','Net','PowerShell') | Where-Object { !$state[$_] }
  if (!$missing) { Write-SetupLog 'Prerequisites already satisfied'; return 0 }
  Write-SetupLog ('Missing: ' + ($missing -join ', '))
  if ($SelectedEdition -eq 'standard') { return 2 }
  if (!$state.Win7) { Write-SetupLog 'Win7 offline updates cannot be applied to this OS'; return 2 }
  if ($state.WMF3) { Write-SetupLog 'Remove WMF 3.0 using Microsoft guidance before WMF 5.1'; return 3 }
  if (Test-RebootPending) { Write-SetupLog 'A pending servicing reboot must finish first'; return 3010 }
  foreach ($item in @(
      @('SSU', ('ssu-' + $Architecture + '.msu')),
      @('SHA2', ('sha2-' + $Architecture + '.msu')),
      @('D3D', ('d3d-' + $Architecture + '.msu')),
      @('Net', 'net472.exe'),
      @('PowerShell', ('wmf-' + $Architecture + '.msu')))) {
    if ($state[$item[0]]) { continue }
    $code = Invoke-OfflineInstaller $item[1] '/q /norestart'
    if ($code -eq 3010 -or $code -eq 1641 -or $code -eq 2359301) { return 3010 }
    if ($code -ne 0 -and $code -ne 2359302) { throw ('Prerequisite failed: ' + $item[0] + ' exit=' + $code) }
    if (Test-RebootPending) { return 3010 }
  }
  $after = Get-PrerequisiteState
  foreach ($key in @('SSU','SHA2','D3D','Net','PowerShell')) {
    if (!$after[$key]) { throw ('Prerequisite remains unavailable: ' + $key) }
  }
  Write-SetupLog 'Offline prerequisites installed and verified'
  return 0
}

if (!$LibraryOnly) {
  try {
    $arch = 'x86'
    if ([IntPtr]::Size -eq 8) { $arch = 'x64' }
    exit (Invoke-Prerequisites $Edition $arch)
  } catch { Write-SetupLog ('ERROR ' + $_.Exception.Message); exit 1 }
}
