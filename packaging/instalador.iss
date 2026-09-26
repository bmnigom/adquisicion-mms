; Instalador de Adquisicion MMS (Inno Setup 6). Se genera con packaging\construir.cmd.
#define AppName "Adquisición MMS"
#define AppVersion "2.0.0"
#define AppExe "AdquisicionMMS.exe"

[Setup]
AppId={{6B0C5E2A-6F7D-4B7B-9C51-2E8F3A1D4C90}
AppName={#AppName}
AppVersion={#AppVersion}
AppPublisher=bmnigom
DefaultDirName={autopf}\AdquisicionMMS
DefaultGroupName={#AppName}
DisableProgramGroupPage=yes
; Sin administrador por defecto (se instala para el usuario); se puede elegir para todos.
PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=dialog
; El Bluetooth de baja energia que usa el sensor requiere Windows 10 o posterior.
MinVersion=10.0
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
OutputDir=..\dist\instalador
OutputBaseFilename=AdquisicionMMS-{#AppVersion}-instalador
SetupIconFile=mms.ico
UninstallDisplayIcon={app}\{#AppExe}
Compression=lzma2/max
SolidCompression=yes
WizardStyle=modern

[Languages]
Name: "es"; MessagesFile: "compiler:Languages\Spanish.isl"

[Tasks]
Name: "desktopicon"; Description: "Crear un acceso directo en el escritorio"; GroupDescription: "Accesos directos:"

[Files]
Source: "..\dist\AdquisicionMMS\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\{#AppName}"; Filename: "{app}\{#AppExe}"
Name: "{group}\{#AppName} (simulación, sin sensor)"; Filename: "{app}\{#AppExe}"; Parameters: "--simulate"
Name: "{group}\Carpeta de datos y reportes"; Filename: "{localappdata}\AdquisicionMMS\data"
Name: "{group}\Manual (LEEME)"; Filename: "{app}\_internal\LEEME.md"
Name: "{autodesktop}\{#AppName}"; Filename: "{app}\{#AppExe}"; Tasks: desktopicon

[Dirs]
Name: "{localappdata}\AdquisicionMMS\data"; Flags: uninsneveruninstall

[Run]
Filename: "{app}\{#AppExe}"; Description: "Abrir {#AppName}"; Flags: nowait postinstall skipifsilent

[Messages]
es.FinishedLabel=La instalación terminó. Los datos y reportes se guardan en %LOCALAPPDATA%\AdquisicionMMS\data y no se borran al desinstalar.
