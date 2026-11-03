param([Parameter(Mandatory=$true)][string]$InstallDirectory,
      [Parameter(Mandatory=$true)][string]$Generation,
      [Parameter(Mandatory=$true)][string]$Version)
# Run after verified extraction. Restore the previous registry values and exact
# shortcut bytes if publishing any part of the new installation fails.
$ErrorActionPreference='Stop'
$snapshots=@()
$links=@()
$temporary=@()
$registry=[Microsoft.Win32.Registry]::LocalMachine
try {
  $root=[IO.Path]::GetFullPath($InstallDirectory).TrimEnd('\')
  $target=[IO.Path]::GetFullPath($Generation).TrimEnd('\')
  if ([IO.Path]::GetDirectoryName($target) -ne [IO.Path]::Combine($root,'versions') -or
      [IO.Path]::GetFileName($target) -notmatch '^0\.[0-9]+\.[0-9]+[-.a-zA-Z0-9]*-[a-f0-9]{12}$') { throw 'Invalid publication generation' }
  foreach($name in @('DeepSeek Harness.exe','uninstall.exe','dsh-owned-files.tsv')) {
    $path=[IO.Path]::Combine($target,$name)
    if (![IO.File]::Exists($path)) {throw ('Publication input missing: '+$name)}
    $item=Get-Item -LiteralPath $path -Force
    while($item) {
      if(($item.Attributes -band [IO.FileAttributes]::ReparsePoint) -ne 0){throw 'Linked publication path'}
      if($item.FullName.TrimEnd('\') -eq $root){break}
      if($item -is [IO.DirectoryInfo]){$item=$item.Parent}else{$item=$item.Directory}
    }
  }
  $specs=@(
    @{Path='Software\DeepSeekHarnessWin7';Values=@{InstallLocation=$root}},
    @{Path='Software\Microsoft\Windows\CurrentVersion\Uninstall\DeepSeekHarnessWin7';Values=@{
      DisplayName='DeepSeek Harness';DisplayVersion=$Version;InstallLocation=$root;
      UninstallString='"'+[IO.Path]::Combine($target,'uninstall.exe')+'"';NoModify=1;NoRepair=1}}
  )
  foreach($spec in $specs) {
    $key=$registry.OpenSubKey($spec.Path)
    $previous=@{}
    try {
      foreach($name in $spec.Values.Keys) {
        if($key -and $key.GetValueNames() -contains $name) {
          $previous[$name]=@{Value=$key.GetValue($name,$null,[Microsoft.Win32.RegistryValueOptions]::DoNotExpandEnvironmentNames);Kind=$key.GetValueKind($name)}
        }
      }
      $snapshots+=,@{Path=$spec.Path;Existed=($null -ne $key);Values=$previous;Names=@($spec.Values.Keys)}
    } finally {if($key){$key.Close()}}
  }
  # CommonStartMenu is unavailable in the CLR 2.0 used by stock Win7 PS2.
  $shell=New-Object -ComObject WScript.Shell
  $menu=[IO.Path]::Combine($shell.SpecialFolders.Item('AllUsersPrograms'),'DeepSeek Harness')
  [void][IO.Directory]::CreateDirectory($menu)
  foreach($name in @('DeepSeek Harness','Uninstall')) {
    $path=[IO.Path]::Combine($menu,$name+'.lnk')
    if([IO.File]::Exists($path) -and ((Get-Item -LiteralPath $path -Force).Attributes -band [IO.FileAttributes]::ReparsePoint)){throw 'Linked shortcut'}
    $links+=,@{Path=$path;Bytes=$(if([IO.File]::Exists($path)){[IO.File]::ReadAllBytes($path)}else{$null})}
    $staged=[IO.Path]::Combine($menu,[Guid]::NewGuid().ToString('N')+'.lnk')
    $temporary+=,$staged
    $shortcut=$shell.CreateShortcut($staged)
    $shortcut.TargetPath=[IO.Path]::Combine($target,$(if($name -eq 'Uninstall'){'uninstall.exe'}else{'DeepSeek Harness.exe'}))
    $shortcut.WorkingDirectory=$target
    $shortcut.Save()
  }
  foreach($spec in $specs) {
    $key=$registry.CreateSubKey($spec.Path)
    try {foreach($name in $spec.Values.Keys){
      $kind=if($spec.Values[$name] -is [int]){[Microsoft.Win32.RegistryValueKind]::DWord}else{[Microsoft.Win32.RegistryValueKind]::String}
      $key.SetValue($name,$spec.Values[$name],$kind)
    }} finally {$key.Close()}
  }
  for($index=0;$index -lt $links.Count;$index++) {
    [IO.File]::Copy($temporary[$index],$links[$index].Path,$true)
  }
  Write-Host 'Installation shortcuts and registry published'
  exit 0
} catch {
  Write-Host $_.Exception.Message
  $failed=$false
  foreach($entry in $links) {
    try {
      if($null -eq $entry.Bytes){if([IO.File]::Exists($entry.Path)){[IO.File]::Delete($entry.Path)}}
      elseif(![IO.File]::Exists($entry.Path) -or [Convert]::ToBase64String([IO.File]::ReadAllBytes($entry.Path)) -ne [Convert]::ToBase64String($entry.Bytes)){[IO.File]::WriteAllBytes($entry.Path,$entry.Bytes)}
    } catch {$failed=$true;Write-Host ('Shortcut rollback failed: '+$_.Exception.Message)}
  }
  foreach($snapshot in $snapshots) {
    try {
      $key=$registry.CreateSubKey($snapshot.Path)
      try {foreach($name in $snapshot.Names){
        if($snapshot.Values.ContainsKey($name)){$old=$snapshot.Values[$name];$key.SetValue($name,$old.Value,$old.Kind)}else{$key.DeleteValue($name,$false)}
      }} finally {$key.Close()}
      if(!$snapshot.Existed) {
        $key=$registry.OpenSubKey($snapshot.Path)
        try {$empty=$key.ValueCount -eq 0 -and $key.SubKeyCount -eq 0}finally{$key.Close()}
        if($empty){$registry.DeleteSubKey($snapshot.Path,$false)}
      }
    } catch {$failed=$true;Write-Host ('Registry rollback failed: '+$_.Exception.Message)}
  }
  if($failed){exit 5}
  exit 1
} finally {
  foreach($path in $temporary){if([IO.File]::Exists($path)){[IO.File]::Delete($path)}}
}
