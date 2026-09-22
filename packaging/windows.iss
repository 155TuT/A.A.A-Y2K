; Build with tools/build.py --installer; version and paths come from Python metadata.
#ifndef AppVersion
  #error AppVersion must be supplied by the build script
#endif

[Setup]
AppId=ArrowAfterArrowY2K
AppName=A.A.A-Y2K
AppVersion={#AppVersion}
AppPublisher=155TuT
AppPublisherURL=https://github.com/155TuT/A.A.A-Y2K
AppSupportURL=https://github.com/155TuT/A.A.A-Y2K/issues
DefaultDirName={localappdata}\Programs\ArrowAfterArrowY2K
DefaultGroupName=A.A.A-Y2K
PrivilegesRequired=lowest
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
MinVersion=10.0
OutputDir={#OutputDir}
OutputBaseFilename={#OutputName}
UninstallDisplayIcon={app}\A.A.A-Y2K.exe
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
CloseApplications=yes
RestartApplications=no
DisableProgramGroupPage=yes
SetupLogging=yes

[Tasks]
Name: "desktopicon"; Description: "Create a desktop shortcut"; Flags: unchecked

[Files]
Source: "{#SourceDir}\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\A.A.A-Y2K"; Filename: "{app}\A.A.A-Y2K.exe"
Name: "{autodesktop}\A.A.A-Y2K"; Filename: "{app}\A.A.A-Y2K.exe"; Tasks: desktopicon

[Run]
Filename: "{app}\A.A.A-Y2K.exe"; Description: "Launch A.A.A-Y2K"; Flags: nowait postinstall skipifsilent

; Deliberately no UninstallDelete entry: user saves live outside {app}.
