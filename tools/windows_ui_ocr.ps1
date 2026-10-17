param([Parameter(Mandatory=$true)][string]$ManifestPath)
# Installed Windows languages only. No language downloads or external service.
$ErrorActionPreference='Stop'
[Console]::OutputEncoding=New-Object System.Text.UTF8Encoding($false)
Add-Type -AssemblyName System.Runtime.WindowsRuntime
$null=[Windows.Storage.Streams.IRandomAccessStream,Windows.Storage.Streams,ContentType=WindowsRuntime]
$null=[Windows.Graphics.Imaging.BitmapDecoder,Windows.Foundation,ContentType=WindowsRuntime]
$null=[Windows.Media.Ocr.OcrEngine,Windows.Foundation,ContentType=WindowsRuntime]
function Await-Operation($Operation,$Type) {
 $method=[System.WindowsRuntimeSystemExtensions].GetMethods() | Where-Object {$_.Name -eq 'AsTask' -and $_.IsGenericMethod -and $_.GetParameters().Count -eq 1 -and $_.GetParameters()[0].ParameterType.Name -eq 'IAsyncOperation`1'} | Select-Object -First 1
 $method.MakeGenericMethod($Type).Invoke($null,@($Operation)).GetAwaiter().GetResult()
}
$engines=@([Windows.Media.Ocr.OcrEngine]::AvailableRecognizerLanguages | Where-Object {$_.LanguageTag -eq 'ru' -or $_.LanguageTag -eq 'ru-RU' -or $_.LanguageTag -eq 'en-US'} | ForEach-Object {[Windows.Media.Ocr.OcrEngine]::TryCreateFromLanguage($_)})
$paths=Get-Content -LiteralPath $ManifestPath -Raw -Encoding UTF8 | ConvertFrom-Json
$results=@(foreach ($path in $paths) {
 $reads=@();$stream=$null;$bitmap=$null
 try {
  $fs=[IO.File]::OpenRead([string]$path);$stream=[System.IO.WindowsRuntimeStreamExtensions]::AsRandomAccessStream($fs)
  $decoder=Await-Operation ([Windows.Graphics.Imaging.BitmapDecoder]::CreateAsync($stream)) ([Windows.Graphics.Imaging.BitmapDecoder])
  $bitmap=Await-Operation ($decoder.GetSoftwareBitmapAsync()) ([Windows.Graphics.Imaging.SoftwareBitmap])
  foreach ($engine in $engines) {
   $r=Await-Operation ($engine.RecognizeAsync($bitmap)) ([Windows.Media.Ocr.OcrResult])
   $reads+=@{language=$engine.RecognizerLanguage.LanguageTag;lines=@($r.Lines | ForEach-Object {@{text=$_.Text;words=@($_.Words | ForEach-Object {@{text=$_.Text;x=$_.BoundingRect.X;y=$_.BoundingRect.Y;width=$_.BoundingRect.Width;height=$_.BoundingRect.Height}})}})}
  }
  @{status='OK';reads=$reads}
 } catch { @{status='UNAVAILABLE';reads=@()} }
 finally {if ($bitmap) {$bitmap.Dispose()};if ($stream) {$stream.Dispose()}}
})
ConvertTo-Json -InputObject $results -Depth 9 -Compress
