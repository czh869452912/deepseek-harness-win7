param([Parameter(Mandatory=$true)][string]$InstallDirectory, [switch]$CheckOnly, [string]$RegisterGeneration, [string]$RemoveGeneration, [string]$LogPath)
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
try {
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
  if($RegisterGeneration) {
    $generation=[IO.Path]::GetFullPath($RegisterGeneration)
    if([IO.Path]::GetDirectoryName($generation) -ne [IO.Path]::Combine($root,'versions')) {throw 'Invalid installation generation'}
    $uninstaller=[IO.Path]::Combine($generation,'uninstall.exe')
    Test-PlainPath $uninstaller $root
    Set-SetupOperation 'register-generation' $uninstaller
    $hash=[Security.Cryptography.SHA256]::Create()
    $stream=[IO.File]::OpenRead($uninstaller)
    try {$digest=[BitConverter]::ToString($hash.ComputeHash($stream)).Replace('-','').ToLowerInvariant()} finally {$stream.Close();$hash.Clear()}
    [IO.File]::AppendAllText([IO.Path]::Combine($generation,'dsh-owned-files.tsv'),$digest+"`tuninstall.exe`r`n",[Text.Encoding]::UTF8)
    exit 0
  }
  Set-SetupOperation 'process-query' $root
  foreach($process in Get-WmiObject Win32_Process -ErrorAction Stop) {
    Set-SetupOperation 'process-path' ('PID='+$process.ProcessId)
    if ($process.ExecutablePath -and $process.ExecutablePath.StartsWith($root+'\',[StringComparison]::OrdinalIgnoreCase)) {
      Write-SetupDiagnostic ('Close DeepSeek Harness and its Host before changing the installation. PID='+$process.ProcessId+' Path='+$process.ExecutablePath); exit 4
    }
  }
  if ($CheckOnly) { exit 0 }
  $versions=[IO.Path]::Combine($root,'versions')
  if (![IO.Directory]::Exists($versions)) { exit 0 }
  Test-PlainPath $versions $root
  Set-SetupOperation 'enumerate-generations' $versions
  $selected=Get-ChildItem -LiteralPath $versions -Force
  if ($RemoveGeneration) {
    $requested=[IO.Path]::GetFullPath($RemoveGeneration).TrimEnd('\')
    if ([IO.Path]::GetDirectoryName($requested) -ne $versions -or [IO.Path]::GetFileName($requested) -notmatch '^0\.[0-9]+\.[0-9]+[-.a-zA-Z0-9]*-[a-f0-9]{12}$') { throw 'Invalid rollback generation' }
    $selected=@($selected | Where-Object {$_.FullName -eq $requested})
  }
  foreach($version in $selected) {
    if (!$version.PSIsContainer -or $version.Name -notmatch '^0\.[0-9]+\.[0-9]+[-.a-zA-Z0-9]*-[a-f0-9]{12}$') { continue }
    $generation=$version.FullName
    Test-PlainPath $generation $root
    $manifest=[IO.Path]::Combine($generation,'dsh-owned-files.tsv')
    if (![IO.File]::Exists($manifest)) { continue }
    Test-PlainPath $manifest $root
    Set-SetupOperation 'read-inventory' $manifest
    $planned=@()
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
        if($digest -eq $fields[0]) {$planned+=,$path} else {Write-SetupDiagnostic ('Preserved modified file: '+$relative)}
      }
    }
    foreach($path in $planned) { Set-SetupOperation 'delete-owned-file' $path; [IO.File]::Delete($path) }
    Set-SetupOperation 'delete-inventory' $manifest
    [IO.File]::Delete($manifest)
    # Remove only now-empty ancestors of owned files. Never enumerate user trees.
    foreach($path in $planned) {
      $parent=[IO.Path]::GetDirectoryName($path)
      while($parent.StartsWith($generation,[StringComparison]::OrdinalIgnoreCase)) {
        try {[IO.Directory]::Delete($parent,$false)} catch {break}
        if($parent -eq $generation){break}
        $parent=[IO.Path]::GetDirectoryName($parent)
      }
    }
    try {[IO.Directory]::Delete($generation,$false)} catch { }
  }
  try {[IO.Directory]::Delete($versions,$false)} catch { }
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
