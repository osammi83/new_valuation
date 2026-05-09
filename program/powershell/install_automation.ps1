param(
    [string]$DailyTime = "08:30",
    [string]$MonthlyTime = "08:00",
    [string]$AssumptionsMonthlyTime = "08:10",
    [string]$TaskPrefix = "UPValuation"
)

$ErrorActionPreference = "Stop"

$scriptRoot = $PSScriptRoot
$projectRoot = Split-Path -Parent (Split-Path -Parent $scriptRoot)
Set-Location $projectRoot

$setupPath = Join-Path $projectRoot "program\powershell\setup_scheduled_tasks.ps1"
if (-not (Test-Path $setupPath)) {
    throw "Missing file: $setupPath"
}

$configPath = Join-Path $projectRoot "up_valuation_config.json"

function Resolve-PythonRunner {
    param([string[]]$Candidates)
    foreach($candidate in $Candidates){
        try {
            if([string]::IsNullOrWhiteSpace($candidate)){
                continue
            }
            if(Test-Path $candidate){
                return [pscustomobject]@{ Exe = $candidate; Args = @() }
            }
            if($candidate -eq 'py -3'){
                & py -3 --version *> $null
                if($LASTEXITCODE -eq 0){
                    return [pscustomobject]@{ Exe = 'py'; Args = @('-3') }
                }
            }
            if($candidate -eq 'python'){
                & python --version *> $null
                if($LASTEXITCODE -eq 0){
                    return [pscustomobject]@{ Exe = 'python'; Args = @() }
                }
            }
        } catch {
        }
    }
    return $null
}

function Find-PythonExecutable {
    $candidates = New-Object System.Collections.Generic.List[string]

    foreach($envName in @('UP_VALUATION_PYTHON', 'PYTHON_EXE', 'PYTHON_PATH')){
        try {
            $envValue = (Get-Item "Env:$envName" -ErrorAction SilentlyContinue).Value
            if($envValue){
                $candidates.Add([string]$envValue)
            }
        } catch {
        }
    }

    foreach($p in @(
        (Join-Path $env:LocalAppData 'Programs\Python\Python312\python.exe'),
        (Join-Path $env:LocalAppData 'Programs\Python\Python311\python.exe'),
        (Join-Path $env:LocalAppData 'Programs\Python\Python310\python.exe'),
        (Join-Path $env:LocalAppData 'Programs\Python\Python39\python.exe'),
        'C:\Python312\python.exe',
        'C:\Python311\python.exe',
        'C:\Python310\python.exe',
        'C:\Python39\python.exe'
    )){
        $candidates.Add($p)
    }

    foreach($root in @(
        'HKCU:\Software\Python\PythonCore',
        'HKLM:\Software\Python\PythonCore',
        'HKLM:\Software\WOW6432Node\Python\PythonCore'
    )){
        if(Test-Path $root){
            Get-ChildItem $root -ErrorAction SilentlyContinue | ForEach-Object {
                $installPath = $null
                try {
                    $installPath = (Get-ItemProperty -Path (Join-Path $_.PSPath 'InstallPath') -ErrorAction Stop).'(default)'
                } catch {
                    try {
                        $installPath = (Get-ItemProperty -Path $_.PSPath -Name '(default)' -ErrorAction Stop).'(default)'
                    } catch {
                    }
                }
                if($installPath){
                    $candidates.Add((Join-Path $installPath 'python.exe'))
                }
            }
        }
    }

    foreach($candidate in @('py -3', 'python')){
        $candidates.Add($candidate)
    }

    $resolved = Resolve-PythonRunner -Candidates ($candidates.ToArray())
    if($resolved){
        return $resolved
    }
    return $null
}

$pythonRunner = Find-PythonExecutable

if(-not $pythonRunner){
    Write-Host "[Setup] Python not found automatically."
    for($attempt = 1; $attempt -le 3 -and -not $pythonRunner; $attempt++){
        $pythonPath = Read-Host "Enter full python.exe path (attempt $attempt/3)"
        if($pythonPath -and (Test-Path $pythonPath)){
            $pythonRunner = [pscustomobject]@{ Exe = $pythonPath; Args = @() }
            break
        }
        Write-Host "[Setup] Invalid path. Example: C:\Users\<user>\AppData\Local\Programs\Python\Python312\python.exe"
    }
}

if(-not $pythonRunner){
    throw "Python executable could not be determined. Install Python 3.12+ or set UP_VALUATION_PYTHON, then rerun install_automation.ps1."
}

$config = [ordered]@{
    pythonPath = if($pythonRunner){ [string]$pythonRunner.Exe } else { '' }
    dailyTime = $DailyTime
    monthlyTime = $MonthlyTime
    assumptionsMonthlyTime = $AssumptionsMonthlyTime
    taskPrefix = $TaskPrefix
}

$config | ConvertTo-Json -Depth 3 | Set-Content -Path $configPath -Encoding utf8
Write-Host "[OK] Saved config: $configPath"

Write-Host "[Install] Registering scheduled tasks..."
& $setupPath -DailyTime $DailyTime -MonthlyTime $MonthlyTime -AssumptionsMonthlyTime $AssumptionsMonthlyTime -TaskPrefix $TaskPrefix

Write-Host ""
Write-Host "[Done] Automation installed"
Write-Host "  - Daily report task"
Write-Host "  - EPS cache monthly refresh task"
Write-Host "  - assumptions.csv monthly refresh task"
Write-Host "  - Config file: $configPath"
Write-Host ""
Write-Host "If task creation fails due to permissions, run PowerShell as Administrator and retry."

