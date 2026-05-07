param()

$ErrorActionPreference = "Stop"

$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$configPath = Join-Path $scriptDir "up_valuation_config.json"

function Write-Status {
    param(
        [string]$Label,
        [string]$Message,
        [string]$Color = "White"
    )
    Write-Host ("[{0}] {1}" -f $Label, $Message) -ForegroundColor $Color
}

if (-not (Test-Path $configPath)) {
    throw "Missing file: $configPath"
}

$config = Get-Content $configPath -Raw | ConvertFrom-Json

Write-Status "INFO" "Config: $configPath" "Cyan"
Write-Status "INFO" "enableGoogleDriveUpload = $($config.enableGoogleDriveUpload)" "Yellow"
Write-Status "INFO" "googleDriveFolderId = $($config.googleDriveFolderId)" "Yellow"
Write-Status "INFO" "googleServiceAccountJsonPath = $($config.googleServiceAccountJsonPath)" "Yellow"
Write-Status "INFO" "pythonPath = $($config.pythonPath)" "Yellow"

if ($config.pythonPath -and (Test-Path $config.pythonPath)) {
    Write-Status "OK" "Python executable exists" "Green"
} else {
    Write-Status "WARN" "Python executable not found or not set" "DarkYellow"
}

if ([string]::IsNullOrWhiteSpace($config.googleDriveFolderId)) {
    Write-Status "WARN" "Google Drive folder ID is empty" "DarkYellow"
} else {
    Write-Status "OK" "Google Drive folder ID is set" "Green"
}

if ([string]::IsNullOrWhiteSpace($config.googleServiceAccountJsonPath)) {
    Write-Status "WARN" "Service account JSON path is empty" "DarkYellow"
} elseif (Test-Path $config.googleServiceAccountJsonPath) {
    Write-Status "OK" "Service account JSON file exists" "Green"
    try {
        $json = Get-Content $config.googleServiceAccountJsonPath -Raw | ConvertFrom-Json
        Write-Status "OK" ("Service account email = {0}" -f $json.client_email) "Green"
    } catch {
        Write-Status "WARN" "Service account JSON could not be parsed" "DarkYellow"
    }
} else {
    Write-Status "WARN" "Service account JSON file not found" "DarkYellow"
}

try {
    $pythonExe = if ($config.pythonPath) { $config.pythonPath } else { "python" }
    & $pythonExe -c "import google.auth; import google.api_core; print('google libs ok')" 2>$null | Out-Null
    if ($LASTEXITCODE -eq 0) {
        Write-Status "OK" "Google API Python libraries are installed" "Green"
    } else {
        Write-Status "WARN" "Google API Python libraries are missing" "DarkYellow"
    }
} catch {
    Write-Status "WARN" "Unable to check Google API Python libraries" "DarkYellow"
}

if ($config.enableGoogleDriveUpload -eq $true -or $config.enableGoogleDriveUpload -eq "true") {
    Write-Status "INFO" "Google Drive upload is enabled" "Cyan"
} else {
    Write-Status "INFO" "Google Drive upload is disabled" "Cyan"
}