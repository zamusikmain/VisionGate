param(
    [ValidateSet('web','batch','export')][string]$Mode='web',
    [ValidateRange(1024,65535)][int]$Port=8080,
    [string]$ArchiveDirectory='',
    [string]$ReportDirectory='reports/samsung-auto',
    [ValidateSet('','legacy','ppocrv5')][string]$OcrEngine='',
    [ValidateSet('original','enhanced')][string]$RecognitionProfile='enhanced'
)
$ErrorActionPreference='Stop'
$projectRoot=$PSScriptRoot
Set-Location -LiteralPath $projectRoot
if (-not $ArchiveDirectory) {
    $ArchiveDirectory=if ($env:SAMSUNG_ARCHIVE_DIR) { $env:SAMSUNG_ARCHIVE_DIR } else { Join-Path $projectRoot 'data/Samsung/original' }
}
if (-not [IO.Path]::IsPathRooted($ArchiveDirectory)) { $ArchiveDirectory=Join-Path $projectRoot $ArchiveDirectory }
$env:SAMSUNG_ARCHIVE_DIR=$ArchiveDirectory
$env:PYTHONPATH="$projectRoot\.python-packages;$projectRoot"
if ($OcrEngine) { $env:SAMSUNG_OCR_ENGINE=$OcrEngine }
$env:SAMSUNG_RECOGNITION_PROFILE=$RecognitionProfile
if ($env:SAMSUNG_OCR_ENGINE -eq 'ppocrv5') {
    $env:PYTHONPATH+=";$projectRoot\.model-packages"
    python -c 'import onnxruntime, pyclipper, yaml'
    if ($LASTEXITCODE -ne 0) { throw 'Local model dependencies missing from selected Python; see docs/samsung-local-run.md' }
}
$env:FRONTEND_DIST=Join-Path $projectRoot 'frontend/dist'
$env:STORE_ANALYSIS_IMAGES='false'
if ($Mode -eq 'web') {
    if (-not (Test-Path (Join-Path $env:FRONTEND_DIST 'index.html'))) { throw 'Build frontend first; see docs/samsung-local-run.md' }
    Write-Host "Samsung local interface: http://127.0.0.1:$Port/samsung"
    python -m uvicorn backend.render_app:create_app --factory --host 127.0.0.1 --port $Port
} elseif ($Mode -eq 'batch') {
    python -m tools.samsung_run --archive-dir $ArchiveDirectory --output-dir $ReportDirectory
} else {
    $exportPython=if ($env:VISIONGATE_EXPORT_PYTHON) { $env:VISIONGATE_EXPORT_PYTHON } else { 'python' }
    & $exportPython -m tools.samsung_export (Join-Path $ReportDirectory 'results.json') (Join-Path $ReportDirectory 'validation.xlsx')
}
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
