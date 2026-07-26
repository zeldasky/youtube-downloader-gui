# 포터블판 재빌드 스크립트
#
#   powershell -ExecutionPolicy Bypass -File build_portable.ps1
#
# ytdl_gui.py 를 수정한 뒤 이걸 실행하면 dist\YouTubeDownloader\ 와 ZIP 이 다시 만들어진다.
# 내장 바이너리(yt-dlp/ffmpeg/qjs)는 이미 받아둔 게 있으면 재사용하고, 없으면 새로 받는다.

$ErrorActionPreference = 'Stop'
$ProgressPreference    = 'SilentlyContinue'

$Root    = $PSScriptRoot

# 파이썬 찾기: PATH 우선, 없으면 흔한 설치 위치를 뒤진다
$Python = (Get-Command python.exe -ErrorAction SilentlyContinue).Source
if (-not $Python) {
    $Python = Get-ChildItem "C:\Python3*\python.exe", "$env:LOCALAPPDATA\Programs\Python\Python3*\python.exe" `
        -ErrorAction SilentlyContinue | Select-Object -First 1 -ExpandProperty FullName
}
if (-not $Python) {
    throw "파이썬을 찾을 수 없습니다. https://www.python.org 에서 설치한 뒤 다시 실행하세요."
}
Write-Host "파이썬: $Python"

$AppName = "YouTubeDownloader"
$ExeName = "YouTube 다운로더.exe"
$Cache   = Join-Path $Root "_bincache"
$Dist    = Join-Path $Root "dist\$AppName"
$Zip     = Join-Path $Root "YouTube다운로더_포터블.zip"

$FFmpegZipUrl = "https://github.com/BtbN/FFmpeg-Builds/releases/download/latest/ffmpeg-n8.1-latest-win64-lgpl-shared-8.1.zip"
$YtDlpUrl     = "https://github.com/yt-dlp/yt-dlp/releases/latest/download/yt-dlp.exe"
$QjsUrl       = "https://github.com/quickjs-ng/quickjs/releases/download/v0.15.1/qjs-windows-x86_64.exe"

New-Item -ItemType Directory -Force -Path $Cache | Out-Null

# ---------------------------------------------------------------- 바이너리 준비
if (-not (Test-Path "$Cache\yt-dlp.exe")) {
    Write-Host "yt-dlp 내려받는 중..."
    Invoke-WebRequest -Uri $YtDlpUrl -OutFile "$Cache\yt-dlp.exe" -UseBasicParsing
}
if (-not (Test-Path "$Cache\qjs.exe")) {
    Write-Host "QuickJS 내려받는 중..."
    Invoke-WebRequest -Uri $QjsUrl -OutFile "$Cache\qjs.exe" -UseBasicParsing
}
if (-not (Test-Path "$Cache\ffx")) {
    Write-Host "ffmpeg 내려받는 중 (약 67MB)..."
    Invoke-WebRequest -Uri $FFmpegZipUrl -OutFile "$Cache\ffmpeg.zip" -UseBasicParsing
    Expand-Archive -Path "$Cache\ffmpeg.zip" -DestinationPath "$Cache\ffx" -Force
    Remove-Item "$Cache\ffmpeg.zip" -Force
}
$FFBin = (Get-ChildItem "$Cache\ffx" -Recurse -Directory | Where-Object { $_.Name -eq 'bin' } | Select-Object -First 1).FullName

# ------------------------------------------------------------------------ 빌드
Write-Host "PyInstaller 빌드 중..."
& $Python -m PyInstaller --noconfirm --windowed --onedir --name $AppName `
    --distpath (Join-Path $Root "dist") `
    --workpath (Join-Path $Root "build") `
    --specpath (Join-Path $Root "build") `
    (Join-Path $Root "ytdl_gui.py") | Out-Null
if ($LASTEXITCODE -ne 0) { throw "PyInstaller 빌드 실패" }

# --noconfirm 이 dist 를 비우므로 빌드 뒤에 bin 을 넣어야 한다
Write-Host "내장 바이너리 배치 중..."
$Bin = Join-Path $Dist "bin"
New-Item -ItemType Directory -Force -Path $Bin | Out-Null
Copy-Item "$Cache\yt-dlp.exe" -Destination "$Bin\yt-dlp.exe" -Force
Copy-Item "$Cache\qjs.exe"    -Destination "$Bin\qjs.exe"    -Force
Get-ChildItem $FFBin | Where-Object { $_.Name -ne 'ffplay.exe' } |
    ForEach-Object { Copy-Item $_.FullName -Destination $Bin -Force }
$license = Join-Path (Split-Path $FFBin -Parent) "LICENSE.txt"
if (Test-Path $license) { Copy-Item $license -Destination "$Bin\FFMPEG-LICENSE.txt" -Force }

# 실행 파일 이름을 한글로
Rename-Item (Join-Path $Dist "$AppName.exe") -NewName $ExeName -Force

# 사용법 문서 동봉
$doc = Join-Path $Root "사용법.txt"
if (Test-Path $doc) { Copy-Item $doc -Destination $Dist -Force }

# ------------------------------------------------------------------- 자가진단
Write-Host "자가진단 실행 중..."
$report = Join-Path $env:TEMP "ytdl_selftest.txt"
if (Test-Path $report) { Remove-Item $report -Force }
& (Join-Path $Dist $ExeName) --selftest
Start-Sleep -Seconds 8
if (Test-Path $report) { Get-Content $report | Write-Host } else { Write-Warning "자가진단 결과 없음" }

# ------------------------------------------------------------------------ ZIP
Write-Host "ZIP 만드는 중..."
if (Test-Path $Zip) { Remove-Item $Zip -Force }
Compress-Archive -Path "$Dist\*" -DestinationPath $Zip -CompressionLevel Optimal

$folderMB = [math]::Round(((Get-ChildItem $Dist -Recurse -File | Measure-Object Length -Sum).Sum / 1MB), 1)
$zipMB    = [math]::Round(((Get-Item $Zip).Length / 1MB), 1)
Write-Host ""
Write-Host "완료" -ForegroundColor Green
Write-Host "  폴더 : $Dist  ($folderMB MB)"
Write-Host "  ZIP  : $Zip  ($zipMB MB)"
