# Arabic Winning Products Scanner - Windows one-click installer
# Run once. It installs/updates requirements, authenticates GitHub if needed,
# creates a startup task, prevents AC sleep, and starts the scanner immediately.

$ErrorActionPreference = 'Stop'
$Repo = 'alasillp-star/dach'
$RepoUrl = 'https://github.com/alasillp-star/dach.git'
$InstallDir = Join-Path $env:LOCALAPPDATA 'ArabicWinningScanner'
$TaskName = 'Arabic Winning Products Scanner'
$Launcher = Join-Path $InstallDir 'run_forever.ps1'
$SelfUrl = 'https://raw.githubusercontent.com/alasillp-star/dach/main/install_windows_scanner.ps1'

function Write-Step($text) { Write-Host "`n==> $text" -ForegroundColor Cyan }
function Have($cmd) { return [bool](Get-Command $cmd -ErrorAction SilentlyContinue) }

# Self-elevate. Piped/remote execution has no reliable PSCommandPath, so download a temp copy.
$identity = [Security.Principal.WindowsIdentity]::GetCurrent()
$principal = New-Object Security.Principal.WindowsPrincipal($identity)
$admin = $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
if (-not $admin) {
    Write-Step 'Requesting Administrator permission'
    $tmp = Join-Path $env:TEMP 'install_arabic_scanner.ps1'
    Invoke-WebRequest -UseBasicParsing $SelfUrl -OutFile $tmp
    Start-Process powershell.exe -Verb RunAs -ArgumentList @('-NoProfile','-ExecutionPolicy','Bypass','-File',"`"$tmp`"")
    exit
}

Write-Step 'Preparing Windows package tools'
if (-not (Have 'winget')) {
    throw 'winget is required. Install Microsoft App Installer from Microsoft Store, then run this installer again.'
}

if (-not (Have 'git')) {
    Write-Step 'Installing Git'
    winget install --id Git.Git -e --accept-package-agreements --accept-source-agreements --silent
    $env:Path += ';C:\Program Files\Git\cmd'
}

if (-not (Have 'python')) {
    Write-Step 'Installing Python 3.11'
    winget install --id Python.Python.3.11 -e --accept-package-agreements --accept-source-agreements --silent
    $pyRoot = Join-Path $env:LOCALAPPDATA 'Programs\Python\Python311'
    $env:Path += ";$pyRoot;$pyRoot\Scripts"
}

if (-not (Have 'gh')) {
    Write-Step 'Installing GitHub CLI'
    winget install --id GitHub.cli -e --accept-package-agreements --accept-source-agreements --silent
    $env:Path += ';C:\Program Files\GitHub CLI'
}

Write-Step 'Checking GitHub authentication'
$authOk = $false
try {
    gh auth status --hostname github.com 2>$null | Out-Null
    if ($LASTEXITCODE -eq 0) { $authOk = $true }
} catch {}
if (-not $authOk) {
    Write-Host 'A GitHub browser window will open once. Sign in with the owner account for alasillp-star.' -ForegroundColor Yellow
    gh auth login --hostname github.com --git-protocol https --web
}
gh auth setup-git | Out-Null

Write-Step 'Preparing scanner files'
if (Test-Path (Join-Path $InstallDir '.git')) {
    Push-Location $InstallDir
    git reset --hard | Out-Null
    git pull --rebase origin main
    Pop-Location
} else {
    if (Test-Path $InstallDir) { Remove-Item $InstallDir -Recurse -Force }
    git clone $RepoUrl $InstallDir
}

Write-Step 'Creating Python environment'
$Venv = Join-Path $InstallDir '.venv'
if (-not (Test-Path (Join-Path $Venv 'Scripts\python.exe'))) {
    python -m venv $Venv
}
$Py = Join-Path $Venv 'Scripts\python.exe'
& $Py -m pip install --upgrade pip
& $Py -m pip install -r (Join-Path $InstallDir 'requirements.txt')

# Configure repository publisher used by scanner.py
Push-Location $InstallDir
git config user.name 'arabic-meta-scanner'
git config user.email 'actions@users.noreply.github.com'
Pop-Location

Write-Step 'Creating always-on launcher'
$launcherContent = @'
$ErrorActionPreference = 'Continue'
$InstallDir = Join-Path $env:LOCALAPPDATA 'ArabicWinningScanner'
$Py = Join-Path $InstallDir '.venv\Scripts\python.exe'
$env:MIN_DAYS = '14'
$env:INTERVAL_SECONDS = '30'
$env:MAX_RESULTS = '20'
$env:RUN_SECONDS = '2147483000'
$env:STATE_PUSH_SECONDS = '300'
Set-Location $InstallDir
while ($true) {
    try {
        git pull --rebase origin main 2>&1 | Out-Host
        & $Py scanner.py 2>&1 | Tee-Object -FilePath (Join-Path $InstallDir 'scanner.log') -Append
    } catch {
        $_ | Out-String | Add-Content (Join-Path $InstallDir 'scanner.log')
    }
    Start-Sleep -Seconds 30
}
'@
Set-Content -Path $Launcher -Value $launcherContent -Encoding UTF8

Write-Step 'Keeping PC awake while plugged in'
try { powercfg /change standby-timeout-ac 0 | Out-Null } catch {}
try { powercfg /change hibernate-timeout-ac 0 | Out-Null } catch {}

Write-Step 'Installing startup task'
$Action = New-ScheduledTaskAction -Execute 'powershell.exe' -Argument "-NoProfile -WindowStyle Hidden -ExecutionPolicy Bypass -File `"$Launcher`""
$TriggerStartup = New-ScheduledTaskTrigger -AtStartup
$Settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -StartWhenAvailable -RestartCount 999 -RestartInterval (New-TimeSpan -Minutes 1) -ExecutionTimeLimit ([TimeSpan]::Zero)
$Principal = New-ScheduledTaskPrincipal -UserId $env:USERNAME -LogonType Interactive -RunLevel Highest
try { Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false -ErrorAction SilentlyContinue } catch {}
Register-ScheduledTask -TaskName $TaskName -Action $Action -Trigger $TriggerStartup -Settings $Settings -Principal $Principal | Out-Null

Write-Step 'Starting scanner now'
Start-ScheduledTask -TaskName $TaskName
Start-Sleep -Seconds 3
$task = Get-ScheduledTask -TaskName $TaskName
Write-Host "Task state: $($task.State)" -ForegroundColor Green
Write-Host "Install directory: $InstallDir" -ForegroundColor Green
Write-Host "Log: $(Join-Path $InstallDir 'scanner.log')" -ForegroundColor Green
Write-Host "`nDONE. The scanner starts automatically with Windows and keeps running while the PC is on." -ForegroundColor Green
Write-Host 'You can close this window.' -ForegroundColor Green
