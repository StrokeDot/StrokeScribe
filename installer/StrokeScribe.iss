; StrokeScribe Windows installer (Inno Setup 6).
; Built by .github/workflows/windows-installer.yml:
;   python tools/build_windows_installer.py
;   ISCC /DAppVersion=<version> installer\StrokeScribe.iss
;
; Installs for the current user (no administrator needed) into
; %LOCALAPPDATA%\Programs\StrokeScribe, so the in-app updater can replace the
; app files later. Your Library, projects, settings and AI models live
; elsewhere and are never touched by installing or uninstalling.

#ifndef AppVersion
  #define AppVersion "0.0.0"
#endif

[Setup]
AppId={{8C2B6F0E-5A61-4F7B-9E52-1E6C0D9B7A31}
AppName=StrokeScribe
AppVersion={#AppVersion}
AppVerName=StrokeScribe {#AppVersion}
AppPublisher=StrokeDot
VersionInfoVersion=0.5.3
ChangesAssociations=yes
DefaultDirName={localappdata}\Programs\StrokeScribe
DefaultGroupName=StrokeScribe
DisableProgramGroupPage=yes
DisableDirPage=auto
PrivilegesRequired=lowest
OutputDir=..\dist
OutputBaseFilename=StrokeScribe-Setup-{#AppVersion}
SetupIconFile=..\assets\strokescribe.ico
UninstallDisplayIcon={app}\assets\strokescribe.ico
UninstallDisplayName=StrokeScribe
Compression=lzma2/max
SolidCompression=yes
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
WizardStyle=modern
CloseApplications=yes

[Tasks]
Name: "desktopicon"; Description: "Create a desktop shortcut"; GroupDescription: "Shortcuts:"

[Files]
Source: "..\build\stage\*"; DestDir: "{app}"; Flags: recursesubdirs createallsubdirs ignoreversion

[Icons]
Name: "{autoprograms}\StrokeScribe"; Filename: "{app}\StrokeScribe.exe"; WorkingDir: "{app}"; IconFilename: "{app}\assets\strokescribe.ico"; AppUserModelID: "StrokeDot.StrokeScribe"; Comment: "Hand-drawn whiteboard animations"
Name: "{autodesktop}\StrokeScribe"; Filename: "{app}\StrokeScribe.exe"; WorkingDir: "{app}"; IconFilename: "{app}\assets\strokescribe.ico"; AppUserModelID: "StrokeDot.StrokeScribe"; Tasks: desktopicon

[Run]
Filename: "{app}\StrokeScribe.exe"; WorkingDir: "{app}"; Description: "Start StrokeScribe"; Flags: nowait postinstall skipifsilent

[UninstallDelete]
; Files added after installing (updates, the update backup, logs, caches).
Type: filesandordirs; Name: "{app}"

[Registry]
; Only our per-user ProgID/capabilities are owned. Never write UserChoice.
Root: HKCU; Subkey: "Software\Classes\StrokeDot.StrokeScribe.Project"; ValueType: string; ValueName: ""; ValueData: "StrokeScribe Project"; Flags: uninsdeletekey
Root: HKCU; Subkey: "Software\Classes\StrokeDot.StrokeScribe.Project\DefaultIcon"; ValueType: string; ValueName: ""; ValueData: """{app}\assets\strokescribe.ico"",0"
Root: HKCU; Subkey: "Software\Classes\StrokeDot.StrokeScribe.Project\shell\open\command"; ValueType: string; ValueName: ""; ValueData: """{app}\StrokeScribe.exe"" ""%1"""
Root: HKCU; Subkey: "Software\Classes\.strokescribe\OpenWithProgids"; ValueType: string; ValueName: "StrokeDot.StrokeScribe.Project"; ValueData: ""; Flags: uninsdeletevalue
Root: HKCU; Subkey: "Software\Classes\.strokescribe"; ValueType: string; ValueName: ""; ValueData: "StrokeDot.StrokeScribe.Project"; Check: MaySetProjectDefault
Root: HKCU; Subkey: "Software\Classes\Applications\StrokeScribe.exe"; ValueType: string; ValueName: "FriendlyAppName"; ValueData: "StrokeScribe"; Flags: uninsdeletekey
Root: HKCU; Subkey: "Software\Classes\Applications\StrokeScribe.exe\SupportedTypes"; ValueType: string; ValueName: ".strokescribe"; ValueData: ""
Root: HKCU; Subkey: "Software\Classes\Applications\StrokeScribe.exe\shell\open\command"; ValueType: string; ValueName: ""; ValueData: """{app}\StrokeScribe.exe"" ""%1"""
Root: HKCU; Subkey: "Software\StrokeDot\StrokeScribe\Capabilities"; ValueType: string; ValueName: "ApplicationName"; ValueData: "StrokeScribe"; Flags: uninsdeletekey
Root: HKCU; Subkey: "Software\StrokeDot\StrokeScribe\Capabilities"; ValueType: string; ValueName: "ApplicationDescription"; ValueData: "StrokeScribe animation projects"
Root: HKCU; Subkey: "Software\StrokeDot\StrokeScribe\Capabilities\FileAssociations"; ValueType: string; ValueName: ".strokescribe"; ValueData: "StrokeDot.StrokeScribe.Project"
Root: HKCU; Subkey: "Software\RegisteredApplications"; ValueType: string; ValueName: "StrokeScribe"; ValueData: "Software\StrokeDot\StrokeScribe\Capabilities"; Flags: uninsdeletevalue

[Code]
function MaySetProjectDefault: Boolean;
var Existing: String;
begin
  Result := (not RegQueryStringValue(HKCU, 'Software\Classes\.strokescribe', '', Existing)) or
    (Existing = '') or (Existing = 'StrokeDot.StrokeScribe.Project');
end;

procedure CurUninstallStepChanged(CurUninstallStep: TUninstallStep);
var Existing: String;
begin
  if CurUninstallStep = usUninstall then
  begin
    if RegQueryStringValue(HKCU, 'Software\Classes\.strokescribe', '', Existing) and
      (Existing = 'StrokeDot.StrokeScribe.Project') then
      RegDeleteValue(HKCU, 'Software\Classes\.strokescribe', '');
  end;
end;
