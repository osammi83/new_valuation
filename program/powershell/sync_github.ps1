param(
    [string]$RemoteName = 'origin',
    [string]$Branch = 'main',
    [string]$CommitPrefix = 'chore: sync'
)

$ErrorActionPreference = 'Stop'
$scriptRoot = $PSScriptRoot
$projectRoot = Split-Path -Parent (Split-Path -Parent $scriptRoot)
Set-Location $projectRoot

$gitCommand = Get-Command git -ErrorAction SilentlyContinue
if(-not $gitCommand){
    $gitCommand = Get-Command git.exe -ErrorAction SilentlyContinue
}

if(-not $gitCommand){
    Write-Host '[Git] git executable not found. Install Git or add it to PATH, then rerun sync_github.ps1.'
    exit 1
}

$status = & $gitCommand.Source -C $projectRoot status --porcelain
if([string]::IsNullOrWhiteSpace($status)){
    Write-Host '[Git] No changes to sync.'
    exit 0
}

& $gitCommand.Source -C $projectRoot add -A
if($LASTEXITCODE -ne 0){
    throw '[Git] git add failed.'
}

$timestamp = Get-Date -Format 'yyyy-MM-dd HH:mm:ss'
$message = "$CommitPrefix $timestamp"
& $gitCommand.Source -C $projectRoot commit -m $message
if($LASTEXITCODE -ne 0){
    throw '[Git] git commit failed.'
}

& $gitCommand.Source -C $projectRoot push $RemoteName $Branch
if($LASTEXITCODE -ne 0){
    throw '[Git] git push failed.'
}

Write-Host "[Git] Synced to $RemoteName/$Branch with message: $message"
