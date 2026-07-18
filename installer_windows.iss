; Inno Setup script for FlatCAM Plus.
; Build the portable distribution first (build_windows.ps1), then compile this
; script with ISCC.exe to produce dist\FlatCAM_Plus_<version>_setup.exe.

#define MyAppName "FlatCAM Plus"
#define MyAppVersion "8.998.12"
#define MyAppPublisher "FlatCAM Plus (Beta)"
#define MyAppURL "https://github.com/Deepankar1993/FlatCAM-Plus"
#define MyAppExeName "FlatCAM_Plus.exe"

[Setup]
AppId={{81283BD6-825F-4D4E-815D-A58B437FFEEE}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher={#MyAppPublisher}
AppPublisherURL={#MyAppURL}
AppSupportURL={#MyAppURL}
DefaultDirName={autopf}\{#MyAppName}
DefaultGroupName={#MyAppName}
UninstallDisplayIcon={app}\{#MyAppExeName}
LicenseFile=LICENSE
; per-user install by default (no UAC, app can write its config next to the exe);
; the dialog still lets the user pick an elevated all-users install
PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=dialog
OutputDir=dist
OutputBaseFilename=FlatCAM_Plus_{#MyAppVersion}_beta_setup
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"; Flags: unchecked

[Files]
Source: "dist\FlatCAM_Plus\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"
Name: "{group}\{cm:UninstallProgram,{#MyAppName}}"; Filename: "{uninstallexe}"
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; Tasks: desktopicon

[Run]
Filename: "{app}\{#MyAppExeName}"; Description: "{cm:LaunchProgram,{#MyAppName}}"; Flags: nowait postinstall skipifsilent
