Unicode true
ManifestSupportedOS all
RequestExecutionLevel admin
SetCompressor /SOLID lzma
!include "MUI2.nsh"
!include "LogicLib.nsh"
!include "WinVer.nsh"
!include "x64.nsh"
Name "DeepSeek Harness ${VERSION} (${EDITION})"
OutFile "${OUTPUT}"
!ifndef ARCHITECTURE
  !define ARCHITECTURE x64
!endif
!if "${ARCHITECTURE}" == "x64"
  InstallDir "$PROGRAMFILES64\DeepSeek Harness"
!else if "${ARCHITECTURE}" == "x86"
  InstallDir "$PROGRAMFILES32\DeepSeek Harness"
!else
  !error "Unsupported desktop architecture"
!endif
InstallDirRegKey HKLM "Software\DeepSeekHarnessWin7" "InstallLocation"
ShowInstDetails show
ShowUninstDetails show
Var PrereqLog
Var Generation
Var PrereqLimited
!ifndef MAX_INSTALL_ROOT
  !define MAX_INSTALL_ROOT 100
!endif
!insertmacro MUI_PAGE_WELCOME
!insertmacro MUI_PAGE_DIRECTORY
!insertmacro MUI_PAGE_INSTFILES
!define MUI_FINISHPAGE_TEXT "DeepSeek Harness was installed. Start it from the Start menu. Your settings and sessions stay in your DSH_HOME."
!define MUI_FINISHPAGE_SHOWREADME "$Generation\resources\app\win7-setup.html"
!define MUI_FINISHPAGE_SHOWREADME_TEXT "View Windows 7 offline setup guide"
!define MUI_FINISHPAGE_SHOWREADME_NOTCHECKED
!define MUI_PAGE_CUSTOMFUNCTION_SHOW ShowEnvironmentGuidance
!insertmacro MUI_PAGE_FINISH
!insertmacro MUI_UNPAGE_CONFIRM
!insertmacro MUI_UNPAGE_INSTFILES
!insertmacro MUI_LANGUAGE "English"

!macro ClaimInstaller
  System::Call 'kernel32::CreateMutexW(p 0, i 0, w "Global\DeepSeekHarnessWin7Installer") p .r0 ?e'
  Pop $1
  ${If} $1 == 183
    MessageBox MB_ICONSTOP "Another DeepSeek Harness installer or uninstaller is running." /SD IDOK
    SetErrorLevel 4
    Abort
  ${EndIf}
!macroend

Function .onInit
  !insertmacro ClaimInstaller
  ${IfNot} ${AtLeastWin7}
    MessageBox MB_ICONSTOP "Windows 7 SP1 or later is required." /SD IDOK
    SetErrorLevel 1
    Abort
  ${EndIf}
  ${If} ${IsWin7}
  ${AndIfNot} ${AtLeastServicePack} 1
    MessageBox MB_ICONSTOP "Windows 7 Service Pack 1 is required." /SD IDOK
    SetErrorLevel 1
    Abort
  ${EndIf}
!if "${ARCHITECTURE}" == "x64"
  ${IfNot} ${RunningX64}
    MessageBox MB_ICONSTOP "This package requires x64 Windows." /SD IDOK
    SetErrorLevel 1
    Abort
  ${EndIf}
!endif
  ${If} ${RunningX64}
    SetRegView 64
  ${Else}
    SetRegView 32
  ${EndIf}
FunctionEnd

Function ValidateInstallDirectory
  StrLen $0 $INSTDIR
  ${If} $0 > ${MAX_INSTALL_ROOT}
    MessageBox MB_ICONSTOP "Choose a shorter installation folder. This Win7 package allows at most ${MAX_INSTALL_ROOT} characters before its version directory." /SD IDOK
    SetErrorLevel 1
    Abort
  ${EndIf}
FunctionEnd
Function .onVerifyInstDir
  Call ValidateInstallDirectory
FunctionEnd

Function ShowEnvironmentGuidance
  ${If} $PrereqLimited == 1
    MessageBox MB_ICONINFORMATION "The application is installed. Windows prerequisites were left unchanged. For improved terminal and automation compatibility, extract the separately distributed dsh-win7-offline-upgrade.zip and follow its guide, or use AIO. You can also open the local guide from this page." /SD IDOK
  ${EndIf}
FunctionEnd

Section "Desktop" SEC_DESKTOP
  Call ValidateInstallDirectory
  InitPluginsDir
  SetOutPath "$PLUGINSDIR"
  File /oname=prerequisites.ps1 "${POLICY}"
  File /oname=uninstall-files.ps1 "${CLEANUP}"
  File /oname=publish-installation.ps1 "${PUBLICATION}"
  GetTempFileName $PrereqLog
  ${DisableX64FSRedirection}
  nsExec::ExecToStack /TIMEOUT=60000 '"$SYSDIR\WindowsPowerShell\v1.0\powershell.exe" -NoProfile -NonInteractive -ExecutionPolicy Bypass -File "$PLUGINSDIR\uninstall-files.ps1" -InstallDirectory "$INSTDIR" -CheckOnly -LogPath "$PrereqLog"'
  Pop $0
  Pop $1
  ${EnableX64FSRedirection}
  DetailPrint "$1"
  FileOpen $2 "$PrereqLog" a
  # Script diagnostics go directly to UTF-8 log, avoiding nsExec stack truncation.
  # Keep the launcher result even when PowerShell could not start.
  FileWrite $2 "Instance check exit=$0$\r$\n"
  FileClose $2
  ${If} $0 == 4
    MessageBox MB_ICONSTOP "DeepSeek Harness is still running. Close its windows and choose Quit from its tray icon, then retry. Web/CLI users must stop the corresponding Host. No running application will be terminated. Details: $1 Log: $PrereqLog" /SD IDOK
    SetErrorLevel 4
    Abort
  ${ElseIf} $0 != 0
    MessageBox MB_ICONSTOP "Setup could not check running applications (exit=$0). See Details and log: $PrereqLog. This does not mean an application is running. On Windows 7, extract dsh-win7-offline-upgrade.zip and run upgrade-win7.bat as administrator, restart if requested, then retry." /SD IDOK
    SetErrorLevel 1
    Abort
  ${EndIf}
!if "${EDITION}" == "aio"
  IfSilent consent_done
  MessageBox MB_OKCANCEL|MB_ICONINFORMATION "AIO will install missing Microsoft prerequisites on Windows 7. It may require restarting and running this installer again before the application can be installed." /SD IDOK IDOK consent_done
    SetErrorLevel 1
    Abort
  consent_done:
  SetOutPath "$PLUGINSDIR\prereq"
  File /r "${PREREQUISITES}\*"
!endif
  ${DisableX64FSRedirection}
  nsExec::ExecToLog /TIMEOUT=1850000 '"$SYSDIR\WindowsPowerShell\v1.0\powershell.exe" -NoProfile -NonInteractive -ExecutionPolicy Bypass -File "$PLUGINSDIR\prerequisites.ps1" -Edition ${EDITION} -Payload "$PLUGINSDIR\prereq" -LogPath "$PrereqLog"'
  Pop $0
  ${EnableX64FSRedirection}
  ${If} $0 == 3010
    DetailPrint "Servicing restart required. Log: $PrereqLog"
    IfSilent reboot_later
    MessageBox MB_YESNO|MB_ICONINFORMATION "Windows must restart. Run this installer again after restarting to continue. Restart now?" /SD IDNO IDNO reboot_later
    Reboot
    reboot_later:
    SetErrorLevel 3010
    Abort
!if "${EDITION}" == "standard"
  ${ElseIf} $0 == 2
    StrCpy $PrereqLimited 1
    DetailPrint "Installing Standard with reduced environment capabilities; no system updates executed. Log: $PrereqLog"
!endif
  ${ElseIf} $0 != 0
    MessageBox MB_ICONSTOP "Prerequisites are unavailable or installation failed. Windows 7 needs SSU KB4490628, SHA-2 KB4474419, D3DCompiler47 KB4019990, .NET 4.7.2 and PowerShell 5.1. WMF 3.0 must first be removed using Microsoft guidance. Standard users can use the AIO installer. Log: $PrereqLog" /SD IDOK
    SetErrorLevel 1
    Abort
  ${EndIf}
  StrCpy $Generation "$INSTDIR\versions\${GENERATION}"
  IfFileExists "$Generation\*" generation_exists
  SetOutPath "$Generation"
  ClearErrors
  # Publish the inventory before extraction, so interrupted extraction can
  # remove verified product bytes without touching any earlier generation.
  File /oname=dsh-owned-files.tsv "${PAYLOAD}\dsh-owned-files.tsv"
  File /r "${PAYLOAD}\*"
  IfErrors install_failed
  WriteUninstaller "$Generation\uninstall.exe"
  IfErrors install_failed
  ${DisableX64FSRedirection}
  nsExec::ExecToLog /TIMEOUT=60000 '"$SYSDIR\WindowsPowerShell\v1.0\powershell.exe" -NoProfile -NonInteractive -ExecutionPolicy Bypass -File "$PLUGINSDIR\uninstall-files.ps1" -InstallDirectory "$INSTDIR" -RegisterGeneration "$Generation"'
  Pop $0
  ${EnableX64FSRedirection}
  ${If} $0 != 0
    Goto install_failed
  ${EndIf}
  ${DisableX64FSRedirection}
  nsExec::ExecToLog /TIMEOUT=60000 '"$SYSDIR\WindowsPowerShell\v1.0\powershell.exe" -NoProfile -NonInteractive -ExecutionPolicy Bypass -File "$PLUGINSDIR\publish-installation.ps1" -InstallDirectory "$INSTDIR" -Generation "$Generation" -Version "${VERSION}"'
  Pop $0
  ${EnableX64FSRedirection}
  ${If} $0 == 5
    MessageBox MB_ICONSTOP "Installation registration could not be restored. Application generations were preserved for inspection." /SD IDOK
    SetErrorLevel 5
    Abort
  ${ElseIf} $0 != 0
    Goto install_failed
  ${EndIf}
  Goto done
  generation_exists:
    MessageBox MB_ICONINFORMATION "This exact application generation already exists. Start the installed application or uninstall it before reinstalling." /SD IDOK
    SetErrorLevel 1
    Abort
  install_failed:
    ${DisableX64FSRedirection}
    nsExec::ExecToLog /TIMEOUT=180000 '"$SYSDIR\WindowsPowerShell\v1.0\powershell.exe" -NoProfile -NonInteractive -ExecutionPolicy Bypass -File "$PLUGINSDIR\uninstall-files.ps1" -InstallDirectory "$INSTDIR" -RemoveGeneration "$Generation"'
    Pop $0
    ${EnableX64FSRedirection}
    MessageBox MB_ICONSTOP "Application extraction failed. Verified new-generation files were rolled back; previous generations and user data have been preserved. Modified or unknown files remain for inspection." /SD IDOK
    SetErrorLevel 1
    Abort
  done:
SectionEnd

Function un.onInit
  !insertmacro ClaimInstaller
  ${If} ${RunningX64}
    SetRegView 64
  ${Else}
    SetRegView 32
  ${EndIf}
  # The uninstaller lives inside versions/<generation>.
  GetFullPathName $INSTDIR "$INSTDIR\..\.."
FunctionEnd
Section "Uninstall"
  InitPluginsDir
  SetOutPath "$PLUGINSDIR"
  File /oname=uninstall-files.ps1 "${CLEANUP}"
  ${DisableX64FSRedirection}
  nsExec::ExecToLog /TIMEOUT=180000 '"$SYSDIR\WindowsPowerShell\v1.0\powershell.exe" -NoProfile -NonInteractive -ExecutionPolicy Bypass -File "$PLUGINSDIR\uninstall-files.ps1" -InstallDirectory "$INSTDIR"'
  Pop $0
  ${EnableX64FSRedirection}
  ${If} $0 != 0
    MessageBox MB_ICONSTOP "Quit DeepSeek Harness first. Uninstall stopped; files and user data were preserved." /SD IDOK
    SetErrorLevel 1
    Abort
  ${EndIf}
  SetShellVarContext all
  Delete "$SMPROGRAMS\DeepSeek Harness\DeepSeek Harness.lnk"
  Delete "$SMPROGRAMS\DeepSeek Harness\Uninstall.lnk"
  RMDir "$SMPROGRAMS\DeepSeek Harness"
  ReadRegStr $0 HKLM "Software\DeepSeekHarnessWin7" "InstallLocation"
  ${If} $0 == $INSTDIR
    DeleteRegKey HKLM "Software\DeepSeekHarnessWin7"
    DeleteRegKey HKLM "Software\Microsoft\Windows\CurrentVersion\Uninstall\DeepSeekHarnessWin7"
  ${EndIf}
  Delete "$EXEPATH"
  RMDir "$INSTDIR"
SectionEnd
