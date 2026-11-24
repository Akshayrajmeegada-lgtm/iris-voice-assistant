param([switch]$Disable)

$ErrorActionPreference = 'Stop'
$startupFolder = [Environment]::GetFolderPath('Startup')
$shortcutPath = Join-Path $startupFolder 'Iris Voice Assistant.lnk'

if ($Disable) {
    if (Test-Path -LiteralPath $shortcutPath) {
        Remove-Item -LiteralPath $shortcutPath
    }
    Write-Host 'Iris startup shortcut removed.'
    return
}

$pythonPath = Join-Path $PSScriptRoot '.venv\Scripts\pythonw.exe'
$mainPath = Join-Path $PSScriptRoot 'main.py'
$modelPath = Join-Path $PSScriptRoot 'vosk-model-small-en-us-0.15\am'
if (!(Test-Path -LiteralPath $pythonPath -PathType Leaf) -or
    !(Test-Path -LiteralPath $mainPath -PathType Leaf) -or
    !(Test-Path -LiteralPath $modelPath -PathType Container)) {
    throw 'Set up Iris in this folder and run main.py before enabling startup.'
}

$shell = New-Object -ComObject WScript.Shell
$shortcut = $shell.CreateShortcut($shortcutPath)
$shortcut.TargetPath = $pythonPath
$shortcut.Arguments = '"' + $mainPath + '"'
$shortcut.WorkingDirectory = $PSScriptRoot
$shortcut.Description = 'Start Iris when you sign in to Windows'
$shortcut.Save()
Write-Host 'Iris will listen in the background without a console at your next Windows sign-in.'
