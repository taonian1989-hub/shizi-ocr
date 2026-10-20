$ErrorActionPreference = 'Stop'
Set-Location -LiteralPath $PSScriptRoot
& '.\.venv\Scripts\python.exe' work_prepare.py
$taskBuildPath = $env:PATH
try {
    # Avoid collecting unrelated tools' ICU/OpenSSL DLLs from the host PATH.
    $env:PATH = "$PSScriptRoot\.venv\Scripts;$env:SystemRoot\System32;$env:SystemRoot"
    & '.\.venv\Scripts\python.exe' -m PyInstaller --clean --noconfirm --windowed --name 拾字 --icon (Join-Path $PSScriptRoot 'work\shizi.ico') --collect-all rapidocr_onnxruntime --copy-metadata rapidocr_onnxruntime --copy-metadata PySide6-Essentials --distpath outputs --workpath work\build --specpath work src\main.py
    if ($LASTEXITCODE -ne 0) { throw '打包失败' }
} finally { $env:PATH = $taskBuildPath }
& '.\.venv\Scripts\python.exe' work_prepare.py
