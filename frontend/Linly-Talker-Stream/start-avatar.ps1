$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $root
$python = Join-Path $root ".venv\Scripts\python.exe"
if (-not (Test-Path $python)) { throw "Avatar environment is missing. Run setup first." }
$model = Join-Path $root "models\wav2lip.pth"
$avatar = Join-Path $root "data\avatars\wav2lip_avatar1"
$missing = @()
if (-not (Test-Path $model)) { $missing += "models\wav2lip.pth" }
if (-not (Test-Path (Join-Path $avatar "coords.pkl"))) { $missing += "data\avatars\wav2lip_avatar1\ (sample avatar files)" }
if ($missing.Count) {
  Write-Host "Missing required avatar files:" -ForegroundColor Yellow
  $missing | ForEach-Object { Write-Host "  $_" }
  Write-Host "See README-INSURA.md for the official model download and placement steps."
  exit 1
}
$env:PYTHONUTF8 = "1"
& $python "src\server\app.py" --config "config\config_insura_windows.yaml"

