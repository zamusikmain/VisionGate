param([string]$ImagePath, [string]$ManifestPath)
# Uses the installed Windows OCR engine only. Never installs language packs or calls a service.
$ErrorActionPreference = 'Stop'
[Console]::OutputEncoding = New-Object System.Text.UTF8Encoding($false)
Add-Type -AssemblyName System.Runtime.WindowsRuntime
$null = [Windows.Storage.StorageFile, Windows.Storage, ContentType=WindowsRuntime]
$null = [Windows.Storage.Streams.IRandomAccessStream, Windows.Storage.Streams, ContentType=WindowsRuntime]
$null = [Windows.Graphics.Imaging.BitmapDecoder, Windows.Foundation, ContentType=WindowsRuntime]
$null = [Windows.Graphics.Imaging.SoftwareBitmap, Windows.Foundation, ContentType=WindowsRuntime]
$null = [Windows.Media.Ocr.OcrEngine, Windows.Foundation, ContentType=WindowsRuntime]
$null = [Windows.Media.Ocr.OcrResult, Windows.Foundation, ContentType=WindowsRuntime]
function Wait-Operation($Operation, $ResultType) {
    $method = [System.WindowsRuntimeSystemExtensions].GetMethods() | Where-Object {
        $_.Name -eq 'AsTask' -and $_.IsGenericMethod -and $_.GetParameters().Count -eq 1 -and
        $_.GetParameters()[0].ParameterType.Name -eq 'IAsyncOperation`1'
    } | Select-Object -First 1
    $task = $method.MakeGenericMethod($ResultType).Invoke($null, @($Operation))
    $task.GetAwaiter().GetResult()
}
$engine = [Windows.Media.Ocr.OcrEngine]::TryCreateFromUserProfileLanguages()
if ($null -eq $engine) { throw 'LOCAL_OCR_LANGUAGE_UNAVAILABLE' }
function Read-ImageText([string]$LocalPath) {
 $fileStream = [System.IO.File]::OpenRead($LocalPath)
 $stream = [System.IO.WindowsRuntimeStreamExtensions]::AsRandomAccessStream($fileStream)
 try {
    $decoder = Wait-Operation ([Windows.Graphics.Imaging.BitmapDecoder]::CreateAsync($stream)) ([Windows.Graphics.Imaging.BitmapDecoder])
    $bitmap = Wait-Operation ($decoder.GetSoftwareBitmapAsync()) ([Windows.Graphics.Imaging.SoftwareBitmap])
    try {
        $result = Wait-Operation ($engine.RecognizeAsync($bitmap)) ([Windows.Media.Ocr.OcrResult])
        $lines = @($result.Lines | ForEach-Object {
            $line = $_
            @{text=$line.Text; words=@($line.Words | ForEach-Object {
                @{text=$_.Text; x=$_.BoundingRect.X; y=$_.BoundingRect.Y; width=$_.BoundingRect.Width; height=$_.BoundingRect.Height}
            })}
        })
        return @{engine='windows-local-ocr'; language=$engine.RecognizerLanguage.LanguageTag; lines=$lines}
    } finally { if ($null -ne $bitmap) { $bitmap.Dispose() } }
 } finally { $stream.Dispose(); $fileStream.Dispose() }
}
if ($ManifestPath) {
 $paths = Get-Content -LiteralPath $ManifestPath -Raw -Encoding UTF8 | ConvertFrom-Json
 $results = @(foreach ($localFile in $paths) {
    try { Read-ImageText ([string]$localFile) } catch { @{engine='windows-local-ocr'; status='OCR_FAILED'; lines=@()} }
 })
 ConvertTo-Json -InputObject $results -Depth 8 -Compress
} elseif ($ImagePath) { Read-ImageText $ImagePath | ConvertTo-Json -Depth 8 -Compress }
else { throw 'IMAGE_INPUT_REQUIRED' }
