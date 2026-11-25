# PS2 -File loses exit codes for advanced scripts. Validate required values in
# the body instead of using Parameter(Mandatory), so NSIS receives 1/4 correctly.
param([string]$InstallDirectory, [switch]$CheckOnly, [switch]$PrepareInstall, [string]$StagedUninstaller, [switch]$DiscardStage, [switch]$RetirePrevious, [string]$LogPath)
$ErrorActionPreference='Stop'
$script:setupStage='environment'
$script:setupPath=$InstallDirectory
function Write-SetupDiagnostic([string]$Text) {
  Write-Host $Text
  if ($LogPath) {
    try { [IO.File]::AppendAllText($LogPath,$Text+[Environment]::NewLine,[Text.Encoding]::UTF8) }
    catch { Write-Host ('Could not write setup diagnostic log: '+$_.Exception.Message) }
  }
}
function Set-SetupOperation([string]$Stage,[string]$Path) {
  $script:setupStage=$Stage
  $script:setupPath=$Path
}
function Test-PlainPath([string]$Path,[string]$Boundary) {
  $current=[IO.Path]::GetFullPath($Path)
  while ($current) {
    Set-SetupOperation 'path-attributes' $current
    # Read only this object's attributes. Avoid the filesystem provider and
    # DirectoryInfo.Parent's additional path-discovery checks on old CLR.
    $attributes=[IO.File]::GetAttributes($current)
    if (($attributes -band [IO.FileAttributes]::ReparsePoint) -ne 0) { throw 'Installation contains a linked path; preserving it' }
    if ($current.TrimEnd('\') -eq $Boundary.TrimEnd('\')) { return }
    $current=[IO.Path]::GetDirectoryName($current)
  }
  throw 'Installation path is outside its boundary'
}
function Collect-EmptyPayloadTree([string]$Path,[Collections.Generic.List[string]]$Directories) {
  foreach($child in Get-ChildItem -LiteralPath $Path -Force) {
    if(!$child.PSIsContainer -or ($child.Attributes -band [IO.FileAttributes]::ReparsePoint)) { return $false }
    if(!(Collect-EmptyPayloadTree $child.FullName $Directories)) { return $false }
  }
  $Directories.Add($Path)
  return $true
}
function Remove-EmptyPayloadTree([string]$Path) {
  if(![IO.Directory]::Exists($Path)) { return }
  # NSIS creates packaged directories even if the file inventory lists no
  # members in them. Keep the whole remainder if it contains files or links.
  $directories=New-Object Collections.Generic.List[string]
  if(Collect-EmptyPayloadTree $Path $directories) {
    foreach($directory in $directories) { [IO.Directory]::Delete($directory,$false) }
  }
}
function Remove-OwnedPayload([string]$generation) {
  if (!(Test-Path -LiteralPath $generation)) { return }
  Test-PlainPath $generation $root
  $manifest=[IO.Path]::Combine($generation,'dsh-owned-files.tsv')
  if (![IO.File]::Exists($manifest)) { return }
  Test-PlainPath $manifest $root
  Set-SetupOperation 'read-inventory' $manifest
  $planned=New-Object Collections.Generic.List[string]
  foreach($line in [IO.File]::ReadAllLines($manifest,[Text.Encoding]::UTF8)) {
    $fields=$line.Split([char]9)
    if($fields.Length -ne 2 -or $fields[0] -notmatch '^[a-f0-9]{64}$') { throw 'Invalid installed file inventory; preserving installation' }
    $relative=$fields[1].Replace('/','\')
    if([IO.Path]::IsPathRooted($relative) -or $relative.Split('\') -contains '..' -or $relative.Contains(':')) { throw 'Unsafe installed path' }
    $path=[IO.Path]::GetFullPath([IO.Path]::Combine($generation,$relative))
    if(!$path.StartsWith($generation+'\',[StringComparison]::OrdinalIgnoreCase)) { throw 'Installed path escapes generation' }
    if([IO.File]::Exists($path)) {
      Test-PlainPath $path $root
      Set-SetupOperation 'hash-owned-file' $path
      $hash=[Security.Cryptography.SHA256]::Create()
      $stream=[IO.File]::OpenRead($path)
      try {$digest=[BitConverter]::ToString($hash.ComputeHash($stream)).Replace('-','').ToLowerInvariant()} finally {$stream.Close();$hash.Clear()}
      if($digest -eq $fields[0]) {[void]$planned.Add($path)} else {Write-SetupDiagnostic ('Preserved modified file: '+$relative)}
    }
  }
  foreach($path in $planned) { Set-SetupOperation 'delete-owned-file' $path; [IO.File]::Delete($path) }
  Set-SetupOperation 'delete-inventory' $manifest
  [IO.File]::Delete($manifest)
  # Remove only now-empty ancestors of owned files. Never enumerate user trees.
  foreach($path in $planned) {
    $parent=[IO.Path]::GetDirectoryName($path)
    while($parent.StartsWith($generation+'\',[StringComparison]::OrdinalIgnoreCase) -or $parent -eq $generation) {
      try {[IO.Directory]::Delete($parent,$false)} catch {break}
      if($parent -eq $generation){break}
      $parent=[IO.Path]::GetDirectoryName($parent)
    }
  }
  Remove-EmptyPayloadTree $generation
}
try {
  if ([string]::IsNullOrEmpty($InstallDirectory)) { throw 'InstallDirectory is required' }
  $identity=[Security.Principal.WindowsIdentity]::GetCurrent()
  $principal=New-Object Security.Principal.WindowsPrincipal($identity)
  $administrator=$principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
  Write-SetupDiagnostic ('Setup environment: PowerShell='+$PSVersionTable.PSVersion+' CLR='+[Environment]::Version+' ProcessBits='+([IntPtr]::Size*8)+' Administrator='+$administrator+' OS='+[Environment]::OSVersion.Version)
  Write-SetupDiagnostic ('Setup request: InstallDirectory='+$InstallDirectory+' CheckOnly='+$CheckOnly)
  Set-SetupOperation 'normalize-install-directory' $InstallDirectory
  $root=[IO.Path]::GetFullPath($InstallDirectory).TrimEnd('\')
  Set-SetupOperation 'install-directory-attributes' $root
  try { $rootAttributes=[IO.File]::GetAttributes($root) }
  catch [IO.FileNotFoundException] { Write-SetupDiagnostic 'Installation directory does not exist; no installed instance to check.'; exit 0 }
  catch [IO.DirectoryNotFoundException] { Write-SetupDiagnostic 'Installation directory does not exist; no installed instance to check.'; exit 0 }
  if (($rootAttributes -band [IO.FileAttributes]::Directory) -eq 0) { throw 'Installation path is not a directory' }
  Test-PlainPath $root ([IO.Path]::GetPathRoot($root))
  $target=[IO.Path]::Combine($root,'app')
  $stage=[IO.Path]::Combine($root,'.dsh-new')
  $backup=[IO.Path]::Combine($root,'.dsh-old')
  if($StagedUninstaller) {
    $uninstaller=[IO.Path]::Combine($stage,'uninstall.exe')
    $manifest=[IO.Path]::Combine($stage,'dsh-owned-files.tsv')
    Test-PlainPath $manifest $root
    Set-SetupOperation 'register-uninstaller' $uninstaller
    $hash=[Security.Cryptography.SHA256]::Create()
    $stream=[IO.File]::OpenRead($StagedUninstaller)
    try {$digest=[BitConverter]::ToString($hash.ComputeHash($stream)).Replace('-','').ToLowerInvariant()} finally {$stream.Close();$hash.Clear()}
    [IO.File]::AppendAllText($manifest,$digest+"`tuninstall.exe`r`n",[Text.Encoding]::UTF8)
    [IO.File]::Copy($StagedUninstaller,$uninstaller,$false)
    exit 0
  }
  if($DiscardStage) { Remove-OwnedPayload $stage; exit 0 }
  Set-SetupOperation 'process-query' $root
  foreach($process in Get-WmiObject Win32_Process -ErrorAction Stop) {
    Set-SetupOperation 'process-path' ('PID='+$process.ProcessId)
    if ($process.ExecutablePath -and $process.ExecutablePath.StartsWith($root+'\',[StringComparison]::OrdinalIgnoreCase)) {
      Write-SetupDiagnostic ('Close DeepSeek Harness and its Host before changing the installation. PID='+$process.ProcessId+' Path='+$process.ExecutablePath); exit 4
    }
  }
  if ($CheckOnly) { exit 0 }
  if($PrepareInstall) {
    if(Test-Path -LiteralPath $stage) {
      Remove-OwnedPayload $stage
      if(Test-Path -LiteralPath $stage) {
        Test-PlainPath $stage $root
        [IO.Directory]::Delete($stage,$false)
      }
    }
    if(Test-Path -LiteralPath $backup) {
      Test-PlainPath $backup $root
      if(![IO.Directory]::Exists($backup)){throw 'Invalid installation backup'}
      if(!(Test-Path -LiteralPath $target) -and [IO.File]::Exists([IO.Path]::Combine($backup,'DeepSeek Harness.exe'))) {
        [IO.Directory]::Move($backup,$target)
      } else {
        # Previous cleanup may have retained user files. Keep them separately
        # so they cannot block the next replacement of the active app.
        $suffix=[Guid]::NewGuid().ToString('N').Substring(0,8)
        [IO.Directory]::Move($backup,[IO.Path]::Combine($root,'.dsh-old-'+$suffix))
      }
    }
    exit 0
  }
  $versions=[IO.Path]::Combine($root,'versions')
  $retired=@($backup)
  foreach($item in Get-ChildItem -LiteralPath $root -Force) {
    if($item.PSIsContainer -and $item.Name -match '^\.dsh-old-[a-f0-9]{8}$') { $retired+=,$item.FullName }
  }
  if(Test-Path -LiteralPath $versions) {
    Test-PlainPath $versions $root
    Set-SetupOperation 'enumerate-generations' $versions
    foreach($item in Get-ChildItem -LiteralPath $versions -Force) {
      if($item.PSIsContainer -and $item.Name -match '^0\.[0-9]+\.[0-9]+[-.a-zA-Z0-9]*-[a-f0-9]{12}$') { $retired+=,$item.FullName }
    }
  }
  if(!$RetirePrevious) { $retired+=@($stage,$target) }
  foreach($path in $retired) { Remove-OwnedPayload $path }
  if([IO.Directory]::Exists($versions)) { try {[IO.Directory]::Delete($versions,$false)} catch { } }
  exit 0
} catch {
  $failure=$_
  Write-SetupDiagnostic ('Setup failure: Stage='+$script:setupStage+' Path='+$script:setupPath)
  Write-SetupDiagnostic ('ErrorId='+$failure.FullyQualifiedErrorId+' Category='+$failure.CategoryInfo)
  Write-SetupDiagnostic ('Location='+$failure.InvocationInfo.PositionMessage)
  Write-SetupDiagnostic ('ScriptStack='+$failure.ScriptStackTrace)
  $exception=$failure.Exception
  while($exception) {
    Write-SetupDiagnostic ('Exception='+$exception.GetType().FullName+' Message='+$exception.Message)
    $exception=$exception.InnerException
  }
  exit 1
}
