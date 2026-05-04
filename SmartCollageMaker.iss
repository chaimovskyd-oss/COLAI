; Inno Setup Script for Smart Collage Maker
; Build the application first with:
;   pyinstaller smart_collage_maker.spec
; Then compile this script with Inno Setup Compiler.

#define MyAppName "Smart Collage Maker"
#define MyAppVersion "1.0.0"
#define MyAppPublisher "Smart Collage Team"
#define MyAppExeName "SmartCollageMaker.exe"
#define MySourceDir "dist\SmartCollageMaker"
#define MyOutputDir "dist"
#define MyReadmeFile "README.md"

#if FileExists("app\assets\icon.ico")
  #define MySetupIconFile "app\assets\icon.ico"
#endif

#if FileExists("LICENSE.txt")
  #define MyLicenseFile "LICENSE.txt"
#endif

#if !FileExists(MySourceDir + "\" + MyAppExeName)
  #error Build output not found. Run "pyinstaller smart_collage_maker.spec --distpath dist --workpath build" before compiling the installer.
#endif

#if !FileExists(MyReadmeFile)
  #error README.md is required for the installer package but was not found.
#endif

[Setup]
AppId={{4D8649C7-E7B2-49A7-A338-085B4DDDBF8A}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher={#MyAppPublisher}
DefaultDirName={localappdata}\Programs\{#MyAppName}
DefaultGroupName={#MyAppName}
AllowNoIcons=yes
OutputBaseFilename=SmartCollageMaker_Setup
OutputDir={#MyOutputDir}
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
PrivilegesRequired=lowest
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
UninstallDisplayIcon={app}\{#MyAppExeName}
#ifdef MySetupIconFile
SetupIconFile={#MySetupIconFile}
#endif
#ifdef MyLicenseFile
LicenseFile={#MyLicenseFile}
#endif

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"
Name: "hebrew"; MessagesFile: "compiler:Languages\Hebrew.isl"

[Tasks]
Name: "desktopicon"; Description: "Create a desktop icon"; GroupDescription: "Additional icons:"; Flags: unchecked

[Files]
Source: "{#MySourceDir}\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs; Components: main
Source: "{#MyReadmeFile}"; DestDir: "{app}"; Flags: ignoreversion; Components: docs
#ifdef MyLicenseFile
Source: "{#MyLicenseFile}"; DestDir: "{app}"; Flags: ignoreversion; Components: docs
#endif

[Icons]
Name: "{group}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; WorkingDir: "{app}"
Name: "{group}\Uninstall {#MyAppName}"; Filename: "{uninstallexe}"
Name: "{userdesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; Tasks: desktopicon; WorkingDir: "{app}"

[Run]
Filename: "{app}\{#MyAppExeName}"; Description: "Launch {#MyAppName}"; Flags: nowait postinstall skipifsilent; WorkingDir: "{app}"

[UninstallDelete]
Type: filesandordirs; Name: "{app}\temp"
Type: filesandordirs; Name: "{app}\cache"

[Components]
Name: "main"; Description: "Smart Collage Maker application"; Types: full compact custom; Flags: fixed
Name: "docs"; Description: "Documentation"; Types: full

[Types]
Name: "full"; Description: "Full installation"
Name: "compact"; Description: "Minimal installation"
Name: "custom"; Description: "Custom installation"; Flags: iscustom
