param([Parameter(Mandatory=$true)][string]$Plan)
# Elevated consumer of real NSIS installers. Product-wide registry and Start
# menu entries are backed up, temporarily directed to fresh owned test roots,
# then restored. Existing application generations and DSH_HOME are not removed.
$ErrorActionPreference='Stop'
$configuration=Get-Content -LiteralPath $Plan -Raw | ConvertFrom-Json
$output=[IO.Path]::GetFullPath($configuration.output)
$report=@{status='running';lanes=@();restored=$false}
$keys=@('HKLM\Software\DeepSeekHarnessWin7','HKLM\Software\Microsoft\Windows\CurrentVersion\Uninstall\DeepSeekHarnessWin7')
$menu=Join-Path ([Environment]::GetFolderPath('CommonStartMenu')) 'Programs\DeepSeek Harness'
$backups=@()
$links=@()
$owned=@()
$initialRoot=$null
function Save-Report { $report | ConvertTo-Json -Depth 30 | Set-Content -LiteralPath (Join-Path $output 'administrator-report.json') -Encoding UTF8 }
function Digest([string]$Path) {
  $hash=[Security.Cryptography.SHA256]::Create();$stream=[IO.File]::OpenRead($Path)
  try{return [BitConverter]::ToString($hash.ComputeHash($stream)).Replace('-','').ToLowerInvariant()}finally{$stream.Close();$hash.Dispose()}
}
function Invoke-Reg([string[]]$Arguments) {
  $start=New-Object Diagnostics.ProcessStartInfo
  $start.FileName='reg.exe';$start.Arguments=($Arguments | ForEach-Object {'"'+$_+'"'}) -join ' '
  $start.UseShellExecute=$false;$start.CreateNoWindow=$true;$start.RedirectStandardOutput=$true;$start.RedirectStandardError=$true
  $process=[Diagnostics.Process]::Start($start)
  $stdout=$process.StandardOutput.ReadToEnd();$stderr=$process.StandardError.ReadToEnd();$process.WaitForExit()
  # reg.exe sends localized success messages to stderr; capture them outside
  # PowerShell's NativeCommandError stream and use only the actual exit code.
  return $process.ExitCode
}
function Invoke-Setup([string]$File,[string]$Root,[string]$Log) {
  $start=New-Object Diagnostics.ProcessStartInfo
  $start.FileName=$File;$start.Arguments='/S /D='+$Root;$start.UseShellExecute=$false;$start.CreateNoWindow=$true
  $process=[Diagnostics.Process]::Start($start)
  if(!$process.WaitForExit(600000)){throw 'Installer exceeded ten minute deadline'}
  [IO.File]::WriteAllText($Log,('exitCode='+$process.ExitCode),[Text.Encoding]::UTF8)
  if($process.ExitCode -ne 0){throw ('Installer failed: '+$process.ExitCode)}
}
function Installed-Root {
  $key=[Microsoft.Win32.Registry]::LocalMachine.OpenSubKey('Software\DeepSeekHarnessWin7')
  try {if($key){return $key.GetValue('InstallLocation')}}finally{if($key){$key.Close()}}
  return $null
}
function Snapshot-Publication {
  $state=@{}
  foreach($path in $keys) {
    $key=[Microsoft.Win32.Registry]::LocalMachine.OpenSubKey($path.Substring(5));$values=@{}
    try {if($key){foreach($name in ($key.GetValueNames() | Sort-Object)){
      $values[$name]=@{kind=$key.GetValueKind($name).ToString();value=$key.GetValue($name,$null,[Microsoft.Win32.RegistryValueOptions]::DoNotExpandEnvironmentNames)}
    }}}finally{if($key){$key.Close()}}
    $state[$path]=$values
  }
  foreach($name in @('DeepSeek Harness.lnk','Uninstall.lnk')){$state[$name]=Digest (Join-Path $menu $name)}
  return ($state | ConvertTo-Json -Depth 10 -Compress)
}
function Collect-EmptyDirectories([string]$Path,[Collections.Generic.List[string]]$Directories) {
  $item=Get-Item -LiteralPath $Path -Force
  if(($item.Attributes -band [IO.FileAttributes]::ReparsePoint) -ne 0){throw 'Linked uninstall remainder; preserving it'}
  foreach($child in Get-ChildItem -LiteralPath $Path -Force) {
    if(!$child.PSIsContainer){throw ('Unexpected file after uninstall; preserved: '+$child.Name)}
    Collect-EmptyDirectories $child.FullName $Directories
  }
  [void]$Directories.Add($Path)
}
try {
  $principal=New-Object Security.Principal.WindowsPrincipal([Security.Principal.WindowsIdentity]::GetCurrent())
  if(!$principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)){throw 'Administrator token required'}
  $report.fixtureCleanup=@()
  foreach($path in $configuration.cleanupRoots) {
    $path=[IO.Path]::GetFullPath($path)
    if([IO.Path]::GetDirectoryName($path).TrimEnd('\') -ne [IO.Path]::GetTempPath().TrimEnd('\') -or [IO.Path]::GetFileName($path) -notmatch '^dsh-life-[0-9a-f]{8}$') {throw 'Historical QA cleanup boundary differs'}
    if(![IO.Directory]::Exists($path)){continue}
    & powershell.exe -NoProfile -NonInteractive -ExecutionPolicy Bypass -File $configuration.cleanupScript -InstallDirectory $path *> (Join-Path $output ('historical-'+[IO.Path]::GetFileName($path)+'.log'))
    if($LASTEXITCODE -ne 0){throw 'Historical QA inventory cleanup refused'}
    $probe=Join-Path $path 'user-preservation-probe.txt'
    if([IO.File]::Exists($probe)) {
      if([IO.File]::ReadAllText($probe,[Text.Encoding]::UTF8) -ne 'owned user preservation probe'){throw 'Historical QA probe changed; preserving it'}
      [IO.File]::Delete($probe)
    }
    $empty=New-Object 'Collections.Generic.List[string]';Collect-EmptyDirectories $path $empty
    foreach($directory in $empty){[IO.Directory]::Delete($directory,$false)}
    $report.fixtureCleanup+=,@{root=$path;status='removed-verified-owned-QA-products'}
  }
  $initialRoot=Installed-Root
  for($index=0;$index -lt $keys.Count;$index++) {
    $path=Join-Path $output ('registry-before-'+$index+'.reg')
    $code=Invoke-Reg -Arguments @('export',$keys[$index],$path,'/y','/reg:64')
    $backups+=,@{Key=$keys[$index];Path=$path;Existed=($code -eq 0)}
  }
  foreach($name in @('DeepSeek Harness.lnk','Uninstall.lnk')) {
    $path=Join-Path $menu $name;$backup=Join-Path $output ('original-'+$name)
    $exists=[IO.File]::Exists($path)
    if($exists){[IO.File]::Copy($path,$backup,$false)}
    $links+=,@{Path=$path;Backup=$backup;Existed=$exists;Sha256=$(if($exists){Digest $path}else{$null})}
  }
  foreach($lane in $configuration.lanes) {
    $directory=Join-Path $output $lane.id;[void][IO.Directory]::CreateDirectory($directory)
    $root=Join-Path ([IO.Path]::GetTempPath()) ('dsh-life-'+[Guid]::NewGuid().ToString('N').Substring(0,8))
    if([IO.Directory]::Exists($root) -or [IO.File]::Exists($root)){throw 'Test root is not fresh'}
    $owned+=,$root
    [void][IO.Directory]::CreateDirectory($root)
    $state=@{id=$lane.id;root=$root;status='running';checks=@()};$report.lanes+=,$state
    $previous=$null
    if($lane.previous) {
      Invoke-Setup $lane.previous $root (Join-Path $directory 'previous-install.log')
      if((Installed-Root) -ne $root){throw 'Previous install registry differs'}
      $previous=(New-Object -ComObject WScript.Shell).CreateShortcut((Join-Path $menu 'DeepSeek Harness.lnk')).TargetPath
      if(![IO.File]::Exists($previous)){throw 'Previous application missing'}
      $state.checks+=,'actual-previous-installer'
    }
    $sentinel=Join-Path $root 'user-preservation-probe.txt';[IO.File]::WriteAllText($sentinel,'owned user preservation probe',[Text.Encoding]::UTF8)
    Invoke-Setup $lane.installer $root (Join-Path $directory 'current-install.log')
    if((Installed-Root) -ne $root){throw 'Current install registry differs'}
    $shell=New-Object -ComObject WScript.Shell
    $executable=$shell.CreateShortcut((Join-Path $menu 'DeepSeek Harness.lnk')).TargetPath
    if($executable -ne (Join-Path $root 'app\DeepSeek Harness.exe')){throw 'Shortcut target differs'}
    if($previous -and $previous -ne $executable -and [IO.File]::Exists($previous)){throw 'Upgrade retained previous executable'}
    $state.checks+=,'real-administrator-install-registry-shortcuts-and-upgrade'
    # Lock the second shortcut to force failure after the first shortcut and
    # registry have been changed. Verify exact restoration of all old values.
    $before=Snapshot-Publication
    $priorHash=Digest $executable
    $stage=Join-Path $root '.dsh-new';[void][IO.Directory]::CreateDirectory($stage)
    foreach($name in @('DeepSeek Harness.exe','uninstall.exe','dsh-owned-files.tsv')){[IO.File]::WriteAllText((Join-Path $stage $name),'publication rollback probe',[Text.Encoding]::UTF8)}
    $locked=[IO.File]::Open((Join-Path $menu 'Uninstall.lnk'),[IO.FileMode]::Open,[IO.FileAccess]::Read,[IO.FileShare]::Read)
    try {
      & powershell.exe -NoProfile -NonInteractive -ExecutionPolicy Bypass -File $configuration.publication -InstallDirectory $root -Version '0.1.5-rc.3' *> (Join-Path $directory 'publication-failure.log')
      $failureCode=$LASTEXITCODE
    } finally {$locked.Close()}
    if($failureCode -ne 1 -or (Snapshot-Publication) -ne $before -or (Digest $executable) -ne $priorHash){throw ('Publication rollback differs: '+$failureCode)}
    foreach($name in @('DeepSeek Harness.exe','uninstall.exe','dsh-owned-files.tsv')){[IO.File]::Delete((Join-Path $stage $name))}
    [IO.Directory]::Delete($stage,$false)
    $state.checks+=,'actual-publication-failure-restores-registry-and-exact-shortcuts'
    @{executable=$executable;root=$root} | ConvertTo-Json | Set-Content -LiteralPath (Join-Path $directory 'installed.json') -Encoding UTF8
    Save-Report
    $ack=Join-Path $directory 'gui-complete.json';$deadline=[DateTime]::UtcNow.AddMinutes(12)
    while(![IO.File]::Exists($ack)) {if([DateTime]::UtcNow -gt $deadline){throw 'Normal-user GUI observer acknowledgement deadline'};Start-Sleep -Milliseconds 200}
    $observed=Get-Content -LiteralPath $ack -Raw | ConvertFrom-Json
    if(!$observed.passed){throw 'Installed GUI observer failed'}
    $state.checks+=,'normal-user-installed-payload-fresh-and-cold'
    $uninstaller=Join-Path ([IO.Path]::GetDirectoryName($executable)) 'uninstall.exe'
    $process=Start-Process -FilePath $uninstaller -ArgumentList '/S' -PassThru -WindowStyle Hidden
    if(!$process.WaitForExit(300000)){throw 'Uninstaller process completion deadline'}
    $deadline=[DateTime]::UtcNow.AddMinutes(5)
    while((Installed-Root) -eq $root -or [IO.File]::Exists($executable) -or
          [IO.File]::Exists((Join-Path $menu 'DeepSeek Harness.lnk')) -or [IO.File]::Exists((Join-Path $menu 'Uninstall.lnk'))) {
      if([DateTime]::UtcNow -gt $deadline){throw 'Uninstaller completion deadline'}
      Start-Sleep -Milliseconds 200
    }
    if(![IO.File]::Exists($sentinel)){throw 'Uninstaller removed user data'}
    if([IO.File]::Exists($executable) -or ($previous -and [IO.File]::Exists($previous))){throw 'Uninstaller retained owned executables'}
    foreach($name in @('DeepSeek Harness.lnk','Uninstall.lnk')){if([IO.File]::Exists((Join-Path $menu $name))){throw 'Uninstaller retained shortcut'}}
    [IO.File]::Delete($sentinel)
    # File inventories cannot own empty directories shipped by older builds.
    # Record those retained directories, then remove only verified empty test
    # fixture directories in child-first order. Unknown files/reparse abort.
    $empty=New-Object 'Collections.Generic.List[string]'
    if([IO.Directory]::Exists($root)){Collect-EmptyDirectories $root $empty}
    $state.emptyInstallDirectoriesRetained=$empty.Count
    foreach($path in $empty){[IO.Directory]::Delete($path,$false)}
    $state.checks+=,'actual-uninstall-preserves-user-file-and-removes-owned-products'
    $state.status='passed';Save-Report
  }
  $report.status='passed'
} catch {$report.status='failed';$report.failure=$_.Exception.Message}
finally {
  try {
    $current=Installed-Root
    $initial=$null
    if($backups.Count -eq 2) {
      if($current -and $owned -notcontains $current -and $current -ne $initialRoot){
        throw 'Unrelated registry installation changed during QA; backups preserved'
      }
      if($current -and $owned -notcontains $current){
        # A failed preflight must not overwrite an unrelated concurrent install.
        $unchanged=$true
        foreach($entry in $links){if($entry.Existed -and (Digest $entry.Path) -ne $entry.Sha256){$unchanged=$false}}
        if(!$unchanged){throw 'Unrelated installation changed during QA; backups preserved'}
      }
      foreach($entry in $backups) {
        $code=Invoke-Reg -Arguments @('delete',$entry.Key,'/f','/reg:64')
        if($entry.Existed){$code=Invoke-Reg -Arguments @('import',$entry.Path,'/reg:64');if($code){throw 'Registry backup restoration failed'}}
      }
      foreach($entry in $links) {
        if($entry.Existed){[void][IO.Directory]::CreateDirectory($menu);[IO.File]::Copy($entry.Backup,$entry.Path,$true);if((Digest $entry.Path) -ne $entry.Sha256){throw 'Restored shortcut hash differs'}}
        elseif([IO.File]::Exists($entry.Path)){[IO.File]::Delete($entry.Path)}
      }
      $report.restored=$true
    }
  } catch {$report.status='failed';$report.restorationFailure=$_.Exception.Message}
  Save-Report
}
if($report.status -ne 'passed' -or !$report.restored){exit 1}
exit 0
