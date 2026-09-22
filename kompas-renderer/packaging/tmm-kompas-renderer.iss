; Unsigned, per-user TMM KOMPAS Renderer setup.
; build_windows.py supplies all /D values.  There is intentionally no
; SignTool directive: SmartScreen may warn because this release is unsigned.

#ifndef AppVersion
#error AppVersion is required (for example /DAppVersion=0.2.0)
#endif
#ifndef DistDir
#error DistDir is required (the PyInstaller onedir output)
#endif
#ifndef ConfigFile
#error ConfigFile is required (the generated strict release config)
#endif
#ifndef OutputDir
#error OutputDir is required (the release artifact directory)
#endif


[Setup]
AppId={{B6D964A9-9AE0-4CF9-AB5C-5F7F55B01A72}
AppName=TMM KOMPAS Renderer
AppVersion={#AppVersion}
AppVerName=TMM KOMPAS Renderer {#AppVersion}
AppPublisher=TMM
DefaultDirName={localappdata}\Programs\TMM Kompas Renderer
DefaultGroupName=TMM KOMPAS Renderer
DisableProgramGroupPage=yes
UninstallDisplayName=TMM KOMPAS Renderer
UninstallDisplayIcon={app}\tmm-kompas-renderer.exe
OutputDir={#OutputDir}
OutputBaseFilename=tmm-kompas-renderer-setup-{#AppVersion}
Compression=lzma2/max
CompressionThreads=1
LZMAUseSeparateProcess=no
SolidCompression=yes
DiskSpanning=no
PrivilegesRequired=lowest
; No PrivilegesRequiredOverridesAllowed directive: elevation overrides stay disabled.
ArchitecturesAllowed=x64compatible
; The fixed renderer processes are terminated in [Code] before file replacement.
; Keep Inno's Restart Manager prompt disabled: upgrades must not ask the user.
CloseApplications=no
RestartApplications=no
[Code]
const
  TH32CS_SNAPPROCESS = $00000002;
  PROCESS_TERMINATE = $0001;
  SYNCHRONIZE = $00100000;
  WAIT_OBJECT_0 = 0;
  PROCESS_WAIT_TIMEOUT = 5000;
  INVALID_HANDLE_VALUE = -1;
  RendererProcessName = 'tmm-kompas-renderer.exe';
  LegacyProcessName = 'tmm-kompas-agent.exe';

type
  TProcessEntry32 = record
    dwSize: Cardinal;
    cntUsage: Cardinal;
    th32ProcessID: Cardinal;
    th32DefaultHeapID: Cardinal;
    th32ModuleID: Cardinal;
    cntThreads: Cardinal;
    th32ParentProcessID: Cardinal;
    pcPriClassBase: Integer;
    dwFlags: Cardinal;
    szExeFile: array[0..259] of Char;
  end;

function CreateToolhelp32Snapshot(dwFlags, th32ProcessID: Cardinal): THandle;
  external 'CreateToolhelp32Snapshot@kernel32.dll stdcall';
function Process32FirstW(hSnapshot: THandle; var lppe: TProcessEntry32): Boolean;
  external 'Process32FirstW@kernel32.dll stdcall';
function Process32NextW(hSnapshot: THandle; var lppe: TProcessEntry32): Boolean;
  external 'Process32NextW@kernel32.dll stdcall';
function OpenProcess(dwDesiredAccess: Cardinal; bInheritHandle: Boolean; dwProcessId: Cardinal): THandle;
  external 'OpenProcess@kernel32.dll stdcall';
function TerminateProcess(hProcess: THandle; uExitCode: Cardinal): Boolean;
  external 'TerminateProcess@kernel32.dll stdcall';
function WaitForSingleObject(hHandle: THandle; dwMilliseconds: Cardinal): Cardinal;
  external 'WaitForSingleObject@kernel32.dll stdcall';
function CloseHandle(hObject: THandle): Boolean;
  external 'CloseHandle@kernel32.dll stdcall';
function ProcessExeName(const Entry: TProcessEntry32): string;
var
  Index: Integer;
begin
  Result := '';
  for Index := 0 to 259 do
  begin
    if Entry.szExeFile[Index] = #0 then
      Break;
    Result := Result + Entry.szExeFile[Index];
  end;
end;


function StopProcessByName(const ProcessName: string): Boolean;
var
  Snapshot: THandle;
  ProcessEntry: TProcessEntry32;
  ProcessHandle: THandle;
begin
  Result := True;
  Snapshot := CreateToolhelp32Snapshot(TH32CS_SNAPPROCESS, 0);
  if Snapshot = INVALID_HANDLE_VALUE then
  begin
    Result := False;
    Exit;
  end;

  try
    ProcessEntry.dwSize := SizeOf(ProcessEntry);
    if not Process32FirstW(Snapshot, ProcessEntry) then
    begin
      Result := False;
      Exit;
    end;

    repeat
      if CompareText(ProcessExeName(ProcessEntry), ProcessName) = 0 then
      begin
        ProcessHandle := OpenProcess(PROCESS_TERMINATE or SYNCHRONIZE, False, ProcessEntry.th32ProcessID);
        if ProcessHandle = 0 then
          Result := False
        else
        begin
          try
            if not TerminateProcess(ProcessHandle, 0) then
              Result := False
            else if WaitForSingleObject(ProcessHandle, PROCESS_WAIT_TIMEOUT) <> WAIT_OBJECT_0 then
              Result := False;
          finally
            CloseHandle(ProcessHandle);
          end;
        end;
      end;
    until not Process32NextW(Snapshot, ProcessEntry);
  finally
    CloseHandle(Snapshot);
  end;
end;

function StopRendererProcesses(): Boolean;
var
  RendererStopped: Boolean;
  LegacyStopped: Boolean;
begin
  RendererStopped := StopProcessByName(RendererProcessName);
  LegacyStopped := StopProcessByName(LegacyProcessName);
  Result := RendererStopped and LegacyStopped;
end;

function InitializeSetup(): Boolean;
begin
  Result := StopRendererProcesses();
  if not Result then
    MsgBox('Не удалось автоматически закрыть работающий рендерер.', mbError, MB_OK);
end;

function InitializeUninstall(): Boolean;
begin
  Result := StopRendererProcesses();
  if not Result then
    MsgBox('Не удалось автоматически закрыть работающий рендерер.', mbError, MB_OK);
end;

[Files]

; Include the complete PyInstaller onedir runtime (Python, tmm_scene_kompas,
; cryptography, pywin32 imports, and fixture/package data).
Source: "{#DistDir}\*"; DestDir: "{app}"; Excludes: "renderer-config.json"; Flags: ignoreversion recursesubdirs createallsubdirs
; Install the generated release config at the exact path passed to the renderer.
Source: "{#ConfigFile}"; DestDir: "{app}"; DestName: "renderer-config.json"; Flags: ignoreversion

[InstallDelete]
; Remove only obsolete files left by pre-renderer releases after the old
; process has been closed by InitializeSetup before files are replaced.
Type: files; Name: "{app}\tmm-kompas-agent.exe"
Type: files; Name: "{app}\agent-config.json"

[Dirs]
; Runtime backing files are user data and survive uninstall.  In particular,
; downloaded CDW files must not be removed by setup cleanup.
Name: "{localappdata}\TMM\KompasRenderer"; Flags: uninsneveruninstall

[Registry]
; Remove the previous-installation HKCU autostart entry so it cannot relaunch.
Root: HKCU; Subkey: "Software\Microsoft\Windows\CurrentVersion\Run"; ValueType: none; ValueName: "TMM KOMPAS Agent"; Flags: deletevalue
; Explicit HKCU autostart; no HKLM writes, service registration, or elevation.
Root: HKCU; Subkey: "Software\Microsoft\Windows\CurrentVersion\Run"; ValueType: string; ValueName: "TMM KOMPAS Renderer"; ValueData: """{app}\tmm-kompas-renderer.exe"" --config ""{app}\renderer-config.json"""; Flags: uninsdeletevalue
[Run]
; InitializeSetup closes the previous process before files are replaced.
; This starts the freshly installed executable with the new config.
Filename: "{app}\tmm-kompas-renderer.exe"; Parameters: "--config ""{app}\renderer-config.json"""; Description: "Start TMM KOMPAS Renderer"; Flags: nowait postinstall

[UninstallDelete]
; Remove only installed program files/config.  Keep %LOCALAPPDATA%\TMM\KompasRenderer.
Type: filesandordirs; Name: "{app}"
