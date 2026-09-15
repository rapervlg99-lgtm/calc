# Выводит локальный стек (порт 8090, docker-compose.yml с паролем nginx) в интернет
# через бесплатный SSH-туннель pinggy и держит его: бесплатная сессия живёт 60 минут,
# после обрыва сторож поднимает новую (адрес меняется!) с растущей паузой.
#
# ssh работает прямо в этом окне: pinggy сам рисует экран со ссылками
# (строки http://… и https://…xxxx.a.free.pinggy.link). Ссылка — https-вариант.
# Времена подключений пишутся в share-url.log рядом со скриптом.
#
#   powershell -ExecutionPolicy Bypass -File dev\scripts\share-tunnel.ps1
#   powershell -ExecutionPolicy Bypass -File dev\scripts\share-tunnel.ps1 -Port 5173
#
# Остановить: Ctrl+C (дважды) или закрыть окно.
param(
    [int]$Port = 8090,
    [string]$Server = "a.pinggy.io"
)
$ErrorActionPreference = "Continue"
$here = Split-Path -Parent $MyInvocation.MyCommand.Path
$logFile = Join-Path $here "share-url.log"

Write-Host "Туннель к localhost:$Port через $Server. Ссылка появится ниже на экране pinggy (строка https://...)." -ForegroundColor Cyan
Write-Host "Если спросит password — просто Enter. Остановить: Ctrl+C." -ForegroundColor Cyan
Write-Host ""

$pause = 15
while ($true) {
    $started = Get-Date
    "$(Get-Date -Format s) старт туннеля -> localhost:$Port" | Add-Content -Encoding UTF8 $logFile
    # -R0: сервер сам выбирает порт; -p 443 проходит через корпоративные фильтры.
    # 127.0.0.1, а не localhost: Windows резолвит localhost в ::1, Docker слушает
    # только IPv4, и посетитель получал пустой ответ (ERR_EMPTY_RESPONSE).
    # StrictHostKeyChecking=no — ключ сервера pinggy меняется между сессиями.
    & ssh -o StrictHostKeyChecking=no -o UserKnownHostsFile=NUL -o LogLevel=ERROR `
        -o ServerAliveInterval=30 -o ServerAliveCountMax=3 -o ExitOnForwardFailure=yes `
        -p 443 -R0:127.0.0.1:$Port $Server
    $code = $LASTEXITCODE
    $lived = [int]((Get-Date) - $started).TotalSeconds
    "$(Get-Date -Format s) туннель закрылся через $lived с (код $code)" | Add-Content -Encoding UTF8 $logFile
    # Долгая сессия (лимит часа) — переподнимаем сразу; короткая — сервис
    # придерживает наш IP, ждём с удвоением 15 -> 30 -> 60 -> 240 с.
    if ($lived -gt 600) { $pause = 15 } else { $pause = [Math]::Min($pause * 2, 240) }
    Write-Host ""
    Write-Host "Соединение закрылось (жило $lived с). Новый туннель через $pause с, адрес сменится." -ForegroundColor Yellow
    Start-Sleep -Seconds $pause
}
