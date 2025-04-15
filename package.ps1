$root = Join-Path -Path (Get-Location).Path -ChildPath "core"
$core = Join-Path -Path $root -ChildPath "*.py"
$commands = Join-Path -Path $root -ChildPath "commands\*.py"
$common = Join-Path -Path $root -ChildPath "common\*.py"
$components = Join-Path -Path $root -ChildPath "components\*.py"
$fetchers = Join-Path -Path $root -ChildPath "fetchers\*.py"
pyinstaller -y -F -p . -n hab .\core\main.py `
    --hidden-import=coloredlogs `
    --hidden-import=asyncio_atexit `
    --hidden-import=httpx `
    --add-data=${core}:"core" `
    --add-data=${commands}:"core\commands" `
    --add-data=${common}:"core\common" `
    --add-data=${components}:"core\components" `
    --add-data=${fetchers}:"core\fetchers"