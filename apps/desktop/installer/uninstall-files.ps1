param([Parameter(Mandatory=$true)][string]$InstallDirectory, [switch]$CheckOnly, [string]$RegisterGeneration, [string]$RemoveGeneration)
$ErrorActionPreference='Stop'
function Test-PlainPath([string]$Path,[string]$Boundary) {
  $item=Get-Item -LiteralPath $Path -Force
  while ($item) {
    if (($item.Attributes -band [IO.FileAttributes]::ReparsePoint) -ne 0) { throw 'Installation contains a linked path; preserving it' }
    if ($item.FullName.TrimEnd('\') -eq $Boundary.TrimEnd('\')) { return }
    if($item -is [IO.DirectoryInfo]){$item=$item.Parent}else{$item=$item.Directory}
  }
  throw 'Installation path is outside its boundary'
}
try {
  $root=[IO.Path]::GetFullPath($InstallDirectory).TrimEnd('\')
  if (![IO.Directory]::Exists($root)) { exit 0 }
  Test-PlainPath $root ([IO.Path]::GetPathRoot($root))
  if($RegisterGeneration) {
    $generation=[IO.Path]::GetFullPath($RegisterGeneration)
    if([IO.Path]::GetDirectoryName($generation) -ne [IO.Path]::Combine($root,'versions')) {throw 'Invalid installation generation'}
    $uninstaller=[IO.Path]::Combine($generation,'uninstall.exe')
    Test-PlainPath $uninstaller $root
    $hash=[Security.Cryptography.SHA256]::Create()
    $stream=[IO.File]::OpenRead($uninstaller)
    try {$digest=[BitConverter]::ToString($hash.ComputeHash($stream)).Replace('-','').ToLowerInvariant()} finally {$stream.Close();$hash.Clear()}
    [IO.File]::AppendAllText([IO.Path]::Combine($generation,'dsh-owned-files.tsv'),$digest+"`tuninstall.exe`r`n",[Text.Encoding]::UTF8)
    exit 0
  }
  foreach($process in Get-WmiObject Win32_Process) {
    if ($process.ExecutablePath -and $process.ExecutablePath.StartsWith($root+'\',[StringComparison]::OrdinalIgnoreCase)) {
      Write-Host ('Close DeepSeek Harness and its Host before changing the installation. PID='+$process.ProcessId+' Path='+$process.ExecutablePath); exit 4
    }
  }
  if ($CheckOnly) { exit 0 }
  $versions=[IO.Path]::Combine($root,'versions')
  if (![IO.Directory]::Exists($versions)) { exit 0 }
  Test-PlainPath $versions $root
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
        $hash=[Security.Cryptography.SHA256]::Create()
        $stream=[IO.File]::OpenRead($path)
        try {$digest=[BitConverter]::ToString($hash.ComputeHash($stream)).Replace('-','').ToLowerInvariant()} finally {$stream.Close();$hash.Clear()}
        if($digest -eq $fields[0]) {$planned+=,$path} else {Write-Host ('Preserved modified file: '+$relative)}
      }
    }
    foreach($path in $planned) { [IO.File]::Delete($path) }
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
} catch {Write-Host $_.Exception.Message;exit 1}
