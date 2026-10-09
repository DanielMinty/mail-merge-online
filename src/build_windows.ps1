$ErrorActionPreference = 'Stop'
$project = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$build = Join-Path $env:TEMP ("web-mail-merge-build-" + [guid]::NewGuid().ToString('N'))

function Run-Checked([string]$program, [string[]]$arguments) {
    & $program @arguments
    if ($LASTEXITCODE -ne 0) { throw "$program exited with status $LASTEXITCODE" }
}

try {
    New-Item -ItemType Directory -Path (Join-Path $build 'src') -Force | Out-Null
    Copy-Item (Join-Path $PSScriptRoot '*.py') -Destination (Join-Path $build 'src')
    Copy-Item (Join-Path $PSScriptRoot '*.js') -Destination (Join-Path $build 'src')
    Copy-Item (Join-Path $PSScriptRoot 'requirements.txt') -Destination (Join-Path $build 'src')
    Copy-Item (Join-Path $PSScriptRoot 'assets') -Destination (Join-Path $build 'src') -Recurse
    Run-Checked 'python' @('-m', 'venv', (Join-Path $build 'venv'))
    $python = Join-Path $build 'venv\Scripts\python.exe'
    $src = Join-Path $build 'src'
    Run-Checked $python @('-m', 'pip', 'install', '-r', (Join-Path $src 'requirements.txt'), 'pyinstaller>=6,<7', 'pillow>=11,<12')
    Run-Checked $python @('-m', 'PyInstaller', '--noconfirm', '--clean', '--windowed', '--onedir',
        '--name', 'Web Mail Merge', '--icon', (Join-Path $src 'assets\app-icon-512.png'),
        '--add-data', "$(Join-Path $src 'assets\app-icon-512.png');assets",
        '--add-data', "$(Join-Path $src 'picker.js');.", '--collect-all', 'playwright',
        '--distpath', (Join-Path $build 'dist'), '--workpath', (Join-Path $build 'work'),
        '--specpath', $build, (Join-Path $src 'mail_merge.py'))
    $archive = Join-Path $project 'Web-Mail-Merge-Windows-x64.zip'
    if (Test-Path $archive) { Remove-Item $archive }
    Compress-Archive -Path (Join-Path $build 'dist\Web Mail Merge') -DestinationPath $archive
    Write-Host "Created $archive"
}
finally {
    if (Test-Path $build) { Remove-Item $build -Recurse -Force }
}
