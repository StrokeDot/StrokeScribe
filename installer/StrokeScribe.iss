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
Name: "{autoprograms}\StrokeScribe"; Filename: "{app}\runtime\pythonw.exe"; Parameters: """{app}\startup.py"""; WorkingDir: "{app}"; IconFilename: "{app}\assets\strokescribe.ico"; AppUserModelID: "StrokeDot.StrokeScribe"; Comment: "Hand-drawn whiteboard animations"
Name: "{autodesktop}\StrokeScribe"; Filename: "{app}\runtime\pythonw.exe"; Parameters: """{app}\startup.py"""; WorkingDir: "{app}"; IconFilename: "{app}\assets\strokescribe.ico"; AppUserModelID: "StrokeDot.StrokeScribe"; Tasks: desktopicon

[Run]
Filename: "{app}\runtime\pythonw.exe"; Parameters: """{app}\startup.py"""; WorkingDir: "{app}"; Description: "Start StrokeScribe"; Flags: nowait postinstall skipifsilent

[UninstallDelete]
; Files added after installing (updates, the update backup, logs, caches).
Type: filesandordirs; Name: "{app}"
