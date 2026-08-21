$ErrorActionPreference = "Stop"

# Smoke against a running ozm-backend (default: compose local on :8080).
$BaseUrl = if ($env:BASE_URL) { $env:BASE_URL } else { "http://localhost:8080" }

Write-Host "== smoke-backend: $BaseUrl =="

Invoke-WebRequest -Uri "$BaseUrl/healthz" -UseBasicParsing | Out-Null
Invoke-RestMethod -Method Get -Uri "$BaseUrl/api/v1/dicts" | Out-Null

$payload = @{
  objectName   = "smoke"
  address      = "Moscow"
  consent      = $true
  frDurability = "2"
  groups       = @(
    @{
      title    = "G1"
      quantity = 1
      elements = @(
        @{
          title    = "B1"
          shape    = "I-beam_"
          dims     = @{ h = 200; b = 100; s = 5.6; t = 8.5; R = 12 }
          frType   = "1"
          htLevel  = 60
          sides    = @{ left = $true; top = $true; right = $true; bottom = $true }
          lengthM  = 6
          quantity = 1
          coat     = "1"
          method   = "1"
        }
      )
    }
  )
} | ConvertTo-Json -Depth 10

Invoke-RestMethod -Method Post -Uri "$BaseUrl/api/v1/calc" -ContentType "application/json" -Body $payload | Out-Null

# OCR /ext (mounted when CALC_OZM_APP_OCR_ENABLED=true)
$code = 0
try {
  Invoke-WebRequest -Uri "$BaseUrl/api/v1/ext/profiles" -UseBasicParsing | Out-Null
  $code = 200
} catch {
  if ($_.Exception.Response) {
    $code = [int]$_.Exception.Response.StatusCode
  } else {
    throw
  }
}

if ($code -eq 404) {
  Write-Host "ext not mounted (OCR disabled) - ok"
} elseif ($code -eq 401) {
  $r = Invoke-WebRequest -Uri "$BaseUrl/api/v1/ext/profiles" -Headers @{ Authorization = "Bearer smoke" } -UseBasicParsing
  if ($r.StatusCode -ne 200) { throw "ext profiles with auth failed: $($r.StatusCode)" }
  Write-Host "ext ok"
} else {
  throw "unexpected /ext status without auth: $code"
}

Write-Host "smoke ok"
