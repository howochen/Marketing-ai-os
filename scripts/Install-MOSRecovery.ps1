$ErrorActionPreference = 'Stop'
$root = Split-Path $PSScriptRoot -Parent
Set-Location -LiteralPath $root
$python = Join-Path $root '.venv\Scripts\python.exe'
& $python -m scripts.runtime_recovery --configure
if ($LASTEXITCODE -ne 0) { throw 'MOS recovery configuration failed; original data retained.' }
$identity = [Security.Principal.WindowsIdentity]::GetCurrent().Name
$installed = Join-Path $root '.threads-local\runtime-recovery\installed\scripts'
New-Item -ItemType Directory -Force -Path $installed | Out-Null
Copy-Item -LiteralPath (Join-Path $PSScriptRoot 'runtime_recovery.py') -Destination $installed -Force
Copy-Item -LiteralPath (Join-Path $PSScriptRoot 'threads_setup.py') -Destination $installed -Force
Set-Content -LiteralPath (Join-Path $installed '__init__.py') -Value '' -Encoding utf8
$runner = Join-Path $root '.threads-local\runtime-recovery\run.py'
@'
import sys
from pathlib import Path
here=Path(__file__).resolve().parent
sys.path.insert(0,str(here/'installed'))
from scripts import threads_setup as setup
setup.ROOT=here.parents[1]
setup.PRIVATE=setup.ROOT/'.threads-local'
from scripts.runtime_recovery import main
raise SystemExit(main())
'@ | Set-Content -LiteralPath $runner -Encoding utf8
$action = New-ScheduledTaskAction -Execute (Join-Path $root '.venv\Scripts\pythonw.exe') -Argument ('"'+$runner+'"') -WorkingDirectory $root
$logon = New-ScheduledTaskTrigger -AtLogOn -User $identity
$periodic = New-ScheduledTaskTrigger -Once -At (Get-Date).AddMinutes(2) -RepetitionInterval (New-TimeSpan -Minutes 2)
$settings = New-ScheduledTaskSettingsSet -MultipleInstances IgnoreNew -ExecutionTimeLimit (New-TimeSpan -Minutes 5) -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -StartWhenAvailable -Hidden
$principal = New-ScheduledTaskPrincipal -UserId $identity -LogonType Interactive -RunLevel Limited
Register-ScheduledTask -TaskName 'MOS Runtime Recovery' -Action $action -Trigger @($logon,$periodic) -Settings $settings -Principal $principal -Description 'Recover existing MOS containers and the approved fixed ngrok URL only; bounded retries, no AI or publishing.' -Force | Out-Null
$docker = Join-Path $env:ProgramFiles 'Docker\Docker\Docker Desktop.exe'
New-ItemProperty -Path 'HKCU:\Software\Microsoft\Windows\CurrentVersion\Run' -Name 'Docker Desktop' -Value ('"'+$docker+'" -Autostart') -PropertyType String -Force | Out-Null
$shell = New-Object -ComObject WScript.Shell
$shortcut = $shell.CreateShortcut((Join-Path ([Environment]::GetFolderPath('Desktop')) 'MOS 自動恢復狀態.lnk'))
$shortcut.TargetPath = 'notepad.exe'
$shortcut.Arguments = '"'+(Join-Path $root '.threads-local\runtime-recovery\status.txt')+'"'
$shortcut.Save()
Start-ScheduledTask -TaskName 'MOS Runtime Recovery'
Write-Output 'MOS logon and two-minute recovery task installed; desktop status shortcut created.'
