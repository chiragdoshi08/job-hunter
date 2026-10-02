[Setup]
AppId=JobHunterLocal
AppName=Job Hunter
AppVersion=0.3.0
DefaultDirName={localappdata}\Programs\Job Hunter
DefaultGroupName=Job Hunter
PrivilegesRequired=lowest
OutputDir={#AppOutput}
OutputBaseFilename=Job-Hunter-0.3.0-Windows-Setup
Compression=lzma2
SolidCompression=yes
UninstallDisplayIcon={app}\Job Hunter.exe
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible

[Files]
Source: "{#AppSource}\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\Job Hunter"; Filename: "{app}\Job Hunter.exe"
Name: "{group}\Stop Job Hunter"; Filename: "{app}\Job Hunter.exe"; Parameters: "--stop"

[Run]
Filename: "{app}\Job Hunter.exe"; Description: "Open Job Hunter"; Flags: nowait postinstall skipifsilent
