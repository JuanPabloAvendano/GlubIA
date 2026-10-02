# ==========================================================================
#  Crea el repositorio git local de GlubIA y lo sube a GitHub (Windows).
#
#    1. Crea en github.com un repositorio PRIVADO vacio llamado "glubia".
#    2. powershell -ExecutionPolicy Bypass -File scripts\crear-repo.ps1 -Usuario TU-USUARIO
#
#  Comprueba que nada pesado ni secreto entra al repositorio antes de subir.
# ==========================================================================
param(
    [Parameter(Mandatory = $true)][string]$Usuario,
    [string]$Repo = "glubia",
    [string]$Nombre = "Juan Pablo Avendano Duque",
    [string]$Correo = ""
)
$ErrorActionPreference = "Stop"
Set-Location (Split-Path -Parent $PSScriptRoot)

if (-not (Get-Command git -ErrorAction SilentlyContinue)) {
    Write-Host "Falta Git. Instalalo con:  winget install Git.Git   (y abre otra consola)"; exit 1
}

# 1. Configuracion de GitHub Actions: se entrego en github-ci\ porque .github\ no
#    se podia escribir de forma remota.
if (Test-Path github-ci) {
    New-Item -ItemType Directory -Force .github | Out-Null
    Copy-Item -Recurse -Force github-ci\* .github\
    Remove-Item -Recurse -Force github-ci
    Write-Host "ok  .github\ en su sitio"
}

# 2. Repositorio local
if (-not (Test-Path .git)) { git init -b main | Out-Null; Write-Host "ok  repositorio creado" }
git config user.name $Nombre
if ($Correo) { git config user.email $Correo }
git add -A

# 3. Nada pesado ni secreto debe quedar preparado para subir
$prohibido = git diff --cached --name-only | Select-String -Pattern '^(modelo_qwen_7b_ov|openvino_env|datos|respaldo_v1|modelos)/|^\.env$|\.glubia_secret|claves\.json|\.db$'
if ($prohibido) {
    Write-Host "ALTO: estos archivos no deben subirse:"; $prohibido | ForEach-Object { "   $_" }
    git reset | Out-Null; exit 1
}
$grande = git diff --cached --name-only | Where-Object { (Test-Path $_) -and (Get-Item $_).Length -gt 50MB }
if ($grande) { Write-Host "ALTO: archivos de mas de 50 MB:"; $grande; git reset | Out-Null; exit 1 }
Write-Host "ok  $((git diff --cached --name-only | Measure-Object).Count) archivos listos, sin modelo ni secretos"

# 4. Primer commit y subida
git commit -m "GlubIA 2.0: servidor, API, contenedor, pipeline y portafolio" | Out-Null
$remoto = "https://github.com/$Usuario/$Repo.git"
if (-not (git remote | Select-String -Quiet '^origin$')) { git remote add origin $remoto }
git push -u origin main
Write-Host ""
Write-Host "Listo: https://github.com/$Usuario/$Repo"
Write-Host "Las pruebas automaticas ya estan corriendo en la pestana Actions."
