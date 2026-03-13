; Genesis Trading System - Inno Setup Script

#define MyAppName "Genesis Trading System"
#define MyAppVersion "1.0.0"
#define MyAppPublisher "Genesis AI"
#define MyAppURL "https://github.com/PILIGRIM76/MT5Projekt-Clean"
#define MyAppExeName "GenesisTrading.exe"

[Setup]
AppId={{A1B2C3D4-E5F6-7890-ABCD-EF1234567890}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher={#MyAppPublisher}
AppPublisherURL={#MyAppURL}
AppSupportURL={#MyAppURL}
AppUpdatesURL={#MyAppURL}
DefaultDirName={autopf}\{#MyAppName}
DefaultGroupName={#MyAppName}
AllowNoIcons=yes
LicenseFile=LICENSE
OutputDir=installer_output
OutputBaseFilename=GenesisTrading_Setup_v{#MyAppVersion}
SetupIconFile=assets\icon.ico.ico
Compression=lzma2/max
SolidCompression=yes
WizardStyle=modern
PrivilegesRequired=admin
ArchitecturesInstallIn64BitMode=x64

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"
Name: "russian"; MessagesFile: "compiler:Languages\Russian.isl"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"; Flags: unchecked

[Files]
Source: "dist\GenesisTrading\{#MyAppExeName}"; DestDir: "{app}"; Flags: ignoreversion
Source: "dist\GenesisTrading\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs
; NOTE: settings.json will be created automatically on first run
; User can configure it manually using QUICK_START.md as reference
Source: "README.md"; DestDir: "{app}"; Flags: ignoreversion
Source: "QUICK_START.md"; DestDir: "{app}"; Flags: ignoreversion
Source: "TROUBLESHOOTING_PROMPT.md"; DestDir: "{app}"; Flags: ignoreversion
Source: "QUICK_FIX_GUIDE.md"; DestDir: "{app}"; Flags: ignoreversion

[Dirs]
Name: "{app}\database"; Permissions: users-full
Name: "{app}\logs"; Permissions: users-full
Name: "{app}\configs"; Permissions: users-full

[Icons]
Name: "{group}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"
Name: "{group}\Quick Start Guide"; Filename: "{app}\QUICK_START.md"
Name: "{group}\Troubleshooting"; Filename: "{app}\TROUBLESHOOTING_PROMPT.md"
Name: "{group}\{cm:UninstallProgram,{#MyAppName}}"; Filename: "{uninstallexe}"
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; Tasks: desktopicon

[Run]
Filename: "{app}\{#MyAppExeName}"; Description: "{cm:LaunchProgram,{#StringChange(MyAppName, '&', '&&')}}"; WorkingDir: "{app}"; Flags: nowait postinstall

[Code]
procedure InitializeWizard;
var
  WelcomeLabel: TNewStaticText;
begin
  WelcomeLabel := TNewStaticText.Create(WizardForm);
  WelcomeLabel.Parent := WizardForm.WelcomePage;
  WelcomeLabel.Caption := 
    'This will install Genesis Trading System on your computer.' + #13#10 + #13#10 +
    'IMPORTANT REQUIREMENTS:' + #13#10 +
    '  • MetaTrader 5 terminal installed' + #13#10 +
    '  • 8GB+ RAM' + #13#10 +
    '  • Windows 10/11' + #13#10 + #13#10 +
    'After installation, you need to:' + #13#10 +
    '  1. Configure configs\settings.json' + #13#10 +
    '  2. Add your MT5 credentials' + #13#10 +
    '  3. Add API keys (optional)' + #13#10 + #13#10 +
    'See QUICK_START.md for detailed instructions.';
  WelcomeLabel.AutoSize := True;
  WelcomeLabel.WordWrap := True;
  WelcomeLabel.Top := WizardForm.WelcomeLabel2.Top + WizardForm.WelcomeLabel2.Height + 20;
  WelcomeLabel.Width := WizardForm.WelcomeLabel2.Width;
end;

function InitializeSetup(): Boolean;
begin
  Result := True;
  if MsgBox('This software is for educational purposes only.' + #13#10 + #13#10 +
            'Trading involves substantial risk of loss.' + #13#10 +
            'Only trade with capital you can afford to lose.' + #13#10 + #13#10 +
            'Do you understand and accept these risks?', 
            mbConfirmation, MB_YESNO) = IDNO then
  begin
    Result := False;
  end;
end;
