#define AppVersion "0.1.0"
[Setup]
AppId={{AAE644B1-8359-4920-AC77-F171D82A3C18}
AppName=CurveDesk
AppVersion={#AppVersion}
DefaultDirName={localappdata}\Programs\CurveDesk
DefaultGroupName=CurveDesk
PrivilegesRequired=lowest
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
OutputDir=..\dist-installer
OutputBaseFilename=CurveDesk-Windows-x64-Setup
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
[Files]
Source: "..\dist\CurveDesk\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs
[Icons]
Name: "{autoprograms}\CurveDesk"; Filename: "{app}\CurveDesk.exe"
Name: "{autodesktop}\CurveDesk"; Filename: "{app}\CurveDesk.exe"
[Run]
Filename: "{app}\CurveDesk.exe"; Description: "Open CurveDesk"; Flags: nowait postinstall skipifsilent
