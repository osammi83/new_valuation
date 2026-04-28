$ErrorActionPreference = 'Stop'
$here = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $here

$configPath = Join-Path $here 'up_valuation_config.json'
$config = $null
if(Test-Path $configPath){
    try {
        $config = Get-Content $configPath -Raw | ConvertFrom-Json
    } catch {
        $config = $null
    }
}

$configuredPython = $null
if($config -and $config.pythonPath){
    $configuredPython = [string]$config.pythonPath
}

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

$pythonRunner = Resolve-PythonRunner -Candidates @($configuredPython, $env:UP_VALUATION_PYTHON, 'py -3', 'python')

if(-not $pythonRunner){
    throw 'Python executable not found. Set UP_VALUATION_PYTHON or install Python 3.12+.'
}

& $pythonRunner.Exe @($pythonRunner.Args) -m pip install -r requirements.txt
& $pythonRunner.Exe @($pythonRunner.Args) refresh_assumptions.py
