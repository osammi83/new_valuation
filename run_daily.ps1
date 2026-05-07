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

$driveUploadEnabled = $false
if($config -and $null -ne $config.enableGoogleDriveUpload){
	$driveUploadEnabled = [bool]$config.enableGoogleDriveUpload
}

$githubAutoSyncEnabled = $false
if($config -and $null -ne $config.enableGithubAutoSync){
	$githubAutoSyncEnabled = [bool]$config.enableGithubAutoSync
}

$githubRemoteName = 'origin'
if($config -and $config.githubRemoteName){
	$githubRemoteName = [string]$config.githubRemoteName
}

$githubBranch = 'main'
if($config -and $config.githubBranch){
	$githubBranch = [string]$config.githubBranch
}

$githubCommitPrefix = 'auto: sync generated changes'
if($config -and $config.githubCommitPrefix){
	$githubCommitPrefix = [string]$config.githubCommitPrefix
}

if($config -and $config.googleDriveFolderId -and [string]::IsNullOrWhiteSpace($env:GOOGLE_DRIVE_FOLDER_ID)){
	$env:GOOGLE_DRIVE_FOLDER_ID = [string]$config.googleDriveFolderId
}

if($config -and $config.googleServiceAccountJsonPath -and [string]::IsNullOrWhiteSpace($env:GOOGLE_SERVICE_ACCOUNT_JSON)){
	$env:GOOGLE_SERVICE_ACCOUNT_JSON = [string]$config.googleServiceAccountJsonPath
}

if($githubAutoSyncEnabled){
	Write-Host '[Info] GitHub auto sync is enabled via config.'
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

# Load persisted credentials into this process so Python subprocesses can use them.
$dartUser = [Environment]::GetEnvironmentVariable('DART_API_KEY', 'User')
if(-not [string]::IsNullOrWhiteSpace($dartUser)){
	$env:DART_API_KEY = $dartUser
}
$krxIdUser = [Environment]::GetEnvironmentVariable('KRX_ID', 'User')
if(-not [string]::IsNullOrWhiteSpace($krxIdUser)){
	$env:KRX_ID = $krxIdUser
}
$krxPwUser = [Environment]::GetEnvironmentVariable('KRX_PW', 'User')
if(-not [string]::IsNullOrWhiteSpace($krxPwUser)){
	$env:KRX_PW = $krxPwUser
}

Write-Host '[Info] Daily run uses existing eps_cache.csv. Refresh separately via run_eps_cache_refresh.ps1 (recommended monthly/biweekly).'
& $pythonRunner.Exe @($pythonRunner.Args) -m pip install -r requirements.txt

# Delegate the daily flow to the Python orchestrator.
Write-Host '[Info] Delegating daily flow to run_pipeline.py...'
& $pythonRunner.Exe @($pythonRunner.Args) run_pipeline.py daily @Args
if($LASTEXITCODE -ne 0){ throw '[ERROR] run_pipeline.py failed' }

if($githubAutoSyncEnabled){
	Write-Host '[Info] Syncing changes to GitHub...'
	& (Join-Path $here 'sync_github.ps1') -RemoteName $githubRemoteName -Branch $githubBranch -CommitPrefix $githubCommitPrefix
	if($LASTEXITCODE -ne 0){
		Write-Warning '[Warn] GitHub auto sync failed. Daily run completed without pushing changes.'
	}
} else {
	Write-Host '[Info] GitHub auto sync skipped.'
}


