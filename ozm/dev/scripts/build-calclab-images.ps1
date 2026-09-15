# Сборка релиз-пакета ОЗМ для скрытой страницы https://calclab.pro/ozm/
# (см. calclab.pro/deploy/OZM.ru.md). Запускать из папки калькулятора (calc/ozm):
#   powershell -File dev\scripts\build-calclab-images.ps1 [-OutDir D:\dev\ozm-release] [-BasePath /ozm/]
#
# Что делает:
#   1. ozm.env в OutDir: POSTGRES_PASSWORD и API_TOKEN (случайные; существующий файл
#      переиспользуется — токен зашивается в бандл и должен оставаться прежним);
#   2. собирает ozm-backend:calclab, ozm-frontend:calclab (VITE_BASE_PATH, API_TOKEN),
#      ozm-ocr:calclab — по одному, две сборки параллельно вешают Docker Desktop;
#   3. docker save всех трёх в ozm-images.tar;
#   4. fonts.tar с чертёжными шрифтами из C:\Windows\Fonts для OCR.
param(
  [string]$OutDir = "D:\dev\ozm-release",
  [string]$BasePath = "/ozm/",
  [switch]$SkipOcr
)
$ErrorActionPreference = "Stop"
[Console]::OutputEncoding = [Text.Encoding]::UTF8

$root = Resolve-Path (Join-Path $PSScriptRoot "..\..")
Set-Location $root
New-Item -ItemType Directory -Force $OutDir | Out-Null

# --- ozm.env -----------------------------------------------------------------
$envFile = Join-Path $OutDir "ozm.env"
function Rand-Hex([int]$bytes) {
  $b = New-Object byte[] $bytes
  [Security.Cryptography.RandomNumberGenerator]::Create().GetBytes($b)
  return ($b | ForEach-Object { $_.ToString("x2") }) -join ""
}
if (Test-Path $envFile) {
  Write-Host "ozm.env уже есть — переиспользую (токен не меняется): $envFile"
} else {
  $content = @"
# Окружение стека ОЗМ на calclab.pro (/opt/ozm/.env). Создано build-calclab-images.ps1 $(Get-Date -Format s)
POSTGRES_DB=ozm
POSTGRES_USER=ozm
POSTGRES_PASSWORD=$(Rand-Hex 16)
# зашит в бандл ozm-frontend:calclab этой сборки — менять только вместе с пересборкой образа
API_TOKEN=$(Rand-Hex 24)
OCRPDF_MAX_PAGES=10
OCRPDF_MAX_SEC_PER_PAGE=300
OCRPDF_MIN_JOB_SEC=600
OCRPDF_TEMPLATE_CACHE_MB=128
OCRPDF_TEMPLATE_DISK_MB=256
CALC_OZM_APP_LOG_LEVEL=info
"@
  [IO.File]::WriteAllText($envFile, $content.Replace("`r`n", "`n"), (New-Object Text.UTF8Encoding $false))
  Write-Host "создан $envFile"
}
$apiToken = (Select-String -Path $envFile -Pattern '^API_TOKEN=(.+)$').Matches[0].Groups[1].Value.Trim()
if (-not $apiToken) { throw "в $envFile нет API_TOKEN" }

# --- образы (по одному) --------------------------------------------------------
function Build($tag, $context, $extra) {
  Write-Host "`n==> docker build $tag ($context)"
  $t0 = Get-Date
  & docker build -t $tag @extra $context
  if ($LASTEXITCODE -ne 0) { throw "сборка $tag не удалась" }
  Write-Host ("    {0} с" -f [math]::Round(((Get-Date) - $t0).TotalSeconds))
}
Build "ozm-backend:calclab"  "backend"  @()
Build "ozm-frontend:calclab" "frontend" @("--build-arg", "VITE_BASE_PATH=$BasePath", "--build-arg", "VITE_AUTH_DEV_TOKEN=$apiToken")
if (-not $SkipOcr) { Build "ozm-ocr:calclab" "ocr" @() }

# --- save --------------------------------------------------------------------
$tar = Join-Path $OutDir "ozm-images.tar"
Write-Host "`n==> docker save -> $tar"
$images = @("ozm-backend:calclab", "ozm-frontend:calclab")
if (-not $SkipOcr) { $images += "ozm-ocr:calclab" }
& docker save -o $tar @images
if ($LASTEXITCODE -ne 0) { throw "docker save не удался" }
Write-Host ("    {0:N0} МБ" -f ((Get-Item $tar).Length / 1MB))

# --- шрифты -------------------------------------------------------------------
$fontsTar = Join-Path $OutDir "fonts.tar"
$fontNames = @("arial.ttf", "arialn.ttf", "isocpeur.ttf", "isocpeui.ttf", "GOST Common.ttf", "GOST type A.ttf", "GOST type B.ttf")
$present = $fontNames | Where-Object { Test-Path (Join-Path "C:\Windows\Fonts" $_) }
$missing = $fontNames | Where-Object { $_ -notin $present }
if ($present) {
  & tar -cf $fontsTar -C "C:\Windows\Fonts" @present
  Write-Host "`n==> fonts.tar: $($present -join ', ')"
}
if ($missing) { Write-Host "    нет в C:\Windows\Fonts (OCR обойдётся без них): $($missing -join ', ')" }

Write-Host @"

Готово. Дальше — по calclab.pro/deploy/OZM.ru.md:
  scp $envFile root@194.67.122.95:/opt/ozm/.env
  scp $tar root@194.67.122.95:/tmp/ozm-images.tar   (затем на сервере: docker load < /tmp/ozm-images.tar)
  scp $fontsTar root@194.67.122.95:/tmp/ && ssh root@194.67.122.95 "tar -xf /tmp/fonts.tar -C /opt/ozm/fonts"
  ssh root@194.67.122.95 "sudo bash /var/www/calclab.pro/deploy/scripts/install-ozm.sh"
"@
