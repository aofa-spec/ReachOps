; Inno Setup script for ReachOps standalone client.
; Compile on Windows:
;   ISCC.exe ReachOps\packaging\ReachOps.iss /DMyAppVersion=0.4.0 /DMyAppBuild=0

#define MyAppName "ReachOps"
#define MyAppPublisher "Aofa"
#define MyAppURL "https://github.com/aofa-spec/ReachOps"
#define MyAppExeName "ReachOps.exe"

#ifndef MyAppVersion
  #define MyAppVersion "0.4.0"
#endif

#ifndef MyAppBuild
  #define MyAppBuild "0"
#endif

#ifndef MyVersionInfoBuild
  #define MyVersionInfoBuild "0"
#endif

#define MyFullVersion MyAppVersion + "." + MyVersionInfoBuild

[Setup]
AppId={{F0B97B8D-85D2-4A61-8B7A-1DA8A3291504}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppVerName={#MyAppName} {#MyAppVersion}
AppPublisher={#MyAppPublisher}
AppPublisherURL={#MyAppURL}
AppSupportURL={#MyAppURL}
AppUpdatesURL={#MyAppURL}
DefaultDirName={localappdata}\Programs\{#MyAppName}
DefaultGroupName={#MyAppName}
AllowNoIcons=yes
DisableDirPage=no
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
CloseApplications=yes
MinVersion=10.0.18362
WizardStyle=modern
Compression=lzma2/max
SolidCompression=yes
OutputDir=..\..\dist\installer
OutputBaseFilename=ReachOps-Setup-{#MyAppVersion}
SetupIconFile=..\..\ico\startup_icon.ico
UninstallDisplayIcon={app}\{#MyAppExeName}
VersionInfoVersion={#MyFullVersion}
VersionInfoCompany={#MyAppPublisher}
VersionInfoDescription=ReachOps Growth Acquisition Workbench
VersionInfoProductName={#MyAppName}
VersionInfoProductVersion={#MyAppVersion}
VersionInfoCopyright=2026 {#MyAppPublisher}
RestartIfNeededByRun=no
AlwaysRestart=no

[Languages]
Name: "en"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"; Flags: checkedonce

[Files]
; PyInstaller output. Runtime data/config/logs are intentionally outside the app dir.
Source: "..\..\dist\ReachOps\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{autoprograms}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; WorkingDir: "{app}"
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; WorkingDir: "{app}"; Tasks: desktopicon
Name: "{autoprograms}\{#MyAppName}\Uninstall {#MyAppName}"; Filename: "{uninstallexe}"; WorkingDir: "{app}"

[Run]
Filename: "{app}\{#MyAppExeName}"; Description: "{cm:LaunchProgram,{#MyAppName}}"; Flags: nowait postinstall skipifsilent shellexec
