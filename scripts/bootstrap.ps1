#Requires -Version 5.1
<#
.SYNOPSIS
    Bootstrap de Enigma en una maquina Windows desde cero (T-501).

.DESCRIPTION
    Deja una maquina Windows lista para correr Enigma: instala uv, Python 3.12,
    las dependencias del proyecto, FFmpeg (shared build), Ollama y sus modelos,
    Docker Desktop, crea el .env y arranca Qdrant.

    El script es IDEMPOTENTE: cada paso comprueba antes de actuar, asi que
    re-ejecutarlo es seguro. NUNCA sobrescribe un .env existente.

    Prerrequisito: tener Git instalado y haber clonado el repositorio. Este
    script vive dentro del repo y se ejecuta desde el (scripts\bootstrap.ps1).

.PARAMETER Check
    Modo solo-verificacion: comprueba el estado de cada dependencia y reporta
    que falta, SIN instalar ni cambiar nada.

.PARAMETER SkipDocker
    No toca Docker Desktop (util si se gestiona aparte). El paso de Qdrant se
    salta si Docker no esta disponible.

.EXAMPLE
    .\scripts\bootstrap.ps1
    Instalacion completa.

.EXAMPLE
    .\scripts\bootstrap.ps1 -Check
    Solo verifica que hay instalado; no cambia nada.
#>
[CmdletBinding()]
param(
    [switch]$Check,
    [switch]$SkipDocker
)

$ErrorActionPreference = 'Stop'
$RepoRoot = Split-Path -Parent $PSScriptRoot

# Modelos de Ollama necesarios para el flujo principal de Enigma.
$OllamaModels = @('qwen2.5:7b', 'nomic-embed-text')

# Resultado de cada componente, para el resumen final.
$Results = [ordered]@{}

# ─── Helpers de salida ──────────────────────────────────────────────────────

function Write-Step { param([string]$Message) Write-Host "`n==> $Message" -ForegroundColor Cyan }
function Write-Ok   { param([string]$Message) Write-Host "  [OK]  $Message" -ForegroundColor Green }
function Write-Warn2 { param([string]$Message) Write-Host "  [!]   $Message" -ForegroundColor Yellow }
function Write-Fail { param([string]$Message) Write-Host "  [X]   $Message" -ForegroundColor Red }

# ─── Helpers de entorno ─────────────────────────────────────────────────────

function Update-SessionPath {
    # Refresca el PATH de la sesion actual desde el registro, para ver
    # herramientas recien instaladas sin reabrir la terminal.
    $machine = [System.Environment]::GetEnvironmentVariable('Path', 'Machine')
    $user = [System.Environment]::GetEnvironmentVariable('Path', 'User')
    $env:Path = "$machine;$user"
}

function Test-Command {
    param([string]$Name)
    return [bool](Get-Command $Name -ErrorAction SilentlyContinue)
}

function Test-WingetPackage {
    param([string]$Id)
    try {
        winget list --exact --id $Id --accept-source-agreements 2>$null | Out-String -OutVariable listed | Out-Null
        return ($LASTEXITCODE -eq 0 -and $listed -match [regex]::Escape($Id))
    } catch {
        return $false
    }
}

function Install-WingetPackage {
    param([string]$Id, [string]$Label)
    if (Test-WingetPackage -Id $Id) {
        Write-Ok "$Label ya instalado"
        $Results[$Label] = 'ok'
        return
    }
    if ($Check) {
        Write-Warn2 "$Label NO instalado (se instalaria: winget $Id)"
        $Results[$Label] = 'falta'
        return
    }
    Write-Host "  Instalando $Label ($Id)..."
    winget install --exact --id $Id --silent `
        --accept-package-agreements --accept-source-agreements
    if ($LASTEXITCODE -ne 0) {
        throw "winget fallo al instalar $Id (codigo $LASTEXITCODE)"
    }
    Update-SessionPath
    Write-Ok "$Label instalado"
    $Results[$Label] = 'instalado'
}

function Resolve-Uv {
    # Devuelve la ruta a uv.exe: del PATH, o buscando en los paquetes de WinGet.
    $cmd = Get-Command uv -ErrorAction SilentlyContinue
    if ($cmd) { return $cmd.Source }
    $wingetPkgs = Join-Path $env:LOCALAPPDATA 'Microsoft\WinGet\Packages'
    if (Test-Path $wingetPkgs) {
        $found = Get-ChildItem -Path $wingetPkgs -Filter 'uv.exe' -Recurse -ErrorAction SilentlyContinue |
            Select-Object -First 1
        if ($found) { return $found.FullName }
    }
    return $null
}

# ─── Inicio ─────────────────────────────────────────────────────────────────

Write-Step 'Enigma - bootstrap de Windows'
Write-Host "  Repositorio: $RepoRoot"
if ($Check) {
    Write-Host '  Modo: -Check (solo verificacion, no se instala nada)' -ForegroundColor Yellow
}
if ($SkipDocker) {
    Write-Host '  Modo: -SkipDocker (no se toca Docker Desktop)' -ForegroundColor Yellow
}

# ─── 1. Prerrequisitos ──────────────────────────────────────────────────────

Write-Step '1/11  Prerrequisitos (winget, git)'
if (-not (Test-Command 'winget')) {
    Write-Fail 'winget no esta disponible. Actualiza "Instalador de aplicaciones" desde Microsoft Store.'
    throw 'winget es obligatorio para el bootstrap.'
}
Write-Ok 'winget disponible'
if (-not (Test-Command 'git')) {
    Write-Warn2 'git no esta en el PATH. Es necesario para sincronizar el Vault (obsidian-git).'
} else {
    Write-Ok 'git disponible'
}

# ─── 2. uv ──────────────────────────────────────────────────────────────────

Write-Step '2/11  uv (gestor de paquetes Python)'
Install-WingetPackage -Id 'astral-sh.uv' -Label 'uv'
$Uv = Resolve-Uv
if (-not $Uv) {
    if ($Check) {
        Write-Warn2 'uv aun no localizable (se instalaria en una ejecucion real)'
    } else {
        throw 'No se encuentra uv.exe tras la instalacion. Reabre la terminal y reintenta.'
    }
} else {
    Write-Ok "uv en: $Uv"
}

# ─── 3. Python 3.12 ─────────────────────────────────────────────────────────

Write-Step '3/11  Python 3.12 (gestionado por uv)'
if (-not $Uv) {
    Write-Warn2 'uv no disponible; no se puede verificar Python 3.12.'
    $Results['Python 3.12'] = 'falta'
} else {
    & $Uv python find 3.12 *> $null
    $hasPython312 = ($LASTEXITCODE -eq 0)
    if ($hasPython312) {
        Write-Ok 'Python 3.12 disponible para uv'
        $Results['Python 3.12'] = 'ok'
    } elseif ($Check) {
        Write-Warn2 'Python 3.12 NO instalado (se haria: uv python install 3.12)'
        $Results['Python 3.12'] = 'falta'
    } else {
        & $Uv python install 3.12
        if ($LASTEXITCODE -ne 0) { throw "uv python install 3.12 fallo (codigo $LASTEXITCODE)" }
        Write-Ok 'Python 3.12 instalado'
        $Results['Python 3.12'] = 'instalado'
    }
}

# ─── 4. Dependencias del proyecto ───────────────────────────────────────────

Write-Step '4/11  Dependencias del proyecto (uv sync)'
$VenvPath = Join-Path $RepoRoot '.venv'
if (-not $Uv) {
    Write-Warn2 'uv no disponible; no se pueden instalar las dependencias.'
    $Results['Dependencias'] = 'falta'
} elseif ($Check) {
    if (Test-Path $VenvPath) {
        Write-Ok 'Entorno .venv presente (uv sync lo mantiene al dia)'
        $Results['Dependencias'] = 'ok'
    } else {
        Write-Warn2 'Sin .venv (se instalarian las dependencias con: uv sync)'
        $Results['Dependencias'] = 'falta'
    }
} else {
    Push-Location $RepoRoot
    try {
        & $Uv sync
        if ($LASTEXITCODE -ne 0) { throw "uv sync fallo (codigo $LASTEXITCODE)" }
    } finally {
        Pop-Location
    }
    Write-Ok 'Dependencias sincronizadas en .venv'
    $Results['Dependencias'] = 'ok'
}

# ─── 5. FFmpeg (shared build) ───────────────────────────────────────────────

Write-Step '5/11  FFmpeg shared build (necesario para pyannote / sentence-transformers)'
Install-WingetPackage -Id 'Gyan.FFmpeg.Shared' -Label 'FFmpeg (shared)'
if (-not $Check) {
    Write-Warn2 'El PATH con FFmpeg se aplica al reabrir la terminal.'
}

# ─── 6. Ollama ──────────────────────────────────────────────────────────────

Write-Step '6/11  Ollama (LLM y embeddings locales)'
Install-WingetPackage -Id 'Ollama.Ollama' -Label 'Ollama'

# ─── 7. Modelos de Ollama ───────────────────────────────────────────────────

Write-Step '7/11  Modelos de Ollama (descarga ~5 GB la primera vez)'
if (-not (Test-Command 'ollama')) {
    if ($Check) {
        Write-Warn2 "Ollama no localizable; se descargarian: $($OllamaModels -join ', ')"
    } else {
        Write-Warn2 'Ollama no esta en el PATH todavia. Reabre la terminal y reejecuta para los modelos.'
    }
    $Results['Modelos Ollama'] = 'falta'
} else {
    $installed = (ollama list 2>$null | Out-String)
    foreach ($model in $OllamaModels) {
        if ($installed -match [regex]::Escape($model)) {
            Write-Ok "modelo $model ya descargado"
        } elseif ($Check) {
            Write-Warn2 "modelo $model NO descargado (se haria: ollama pull $model)"
        } else {
            Write-Host "  Descargando $model ..."
            ollama pull $model
            if ($LASTEXITCODE -ne 0) { throw "ollama pull $model fallo (codigo $LASTEXITCODE)" }
            Write-Ok "modelo $model descargado"
        }
    }
    $Results['Modelos Ollama'] = 'ok'
}

# ─── 8. Docker Desktop ──────────────────────────────────────────────────────

Write-Step '8/11  Docker Desktop (para Qdrant)'
$DockerReady = $false
if ($SkipDocker) {
    Write-Warn2 'Omitido por -SkipDocker.'
    $Results['Docker'] = 'omitido'
} else {
    if (Test-Command 'docker') {
        docker info *> $null
        if ($LASTEXITCODE -eq 0) {
            $DockerReady = $true
            Write-Ok 'Docker operativo'
            $Results['Docker'] = 'ok'
        } else {
            Write-Warn2 'Docker instalado pero el daemon no responde. Arranca Docker Desktop.'
            $Results['Docker'] = 'instalado (daemon parado)'
        }
    } else {
        Install-WingetPackage -Id 'Docker.DockerDesktop' -Label 'Docker Desktop'
        Write-Warn2 'Docker Desktop puede requerir REINICIAR Windows y activar WSL2.'
        Write-Warn2 'Tras reiniciar y arrancar Docker, reejecuta este script para levantar Qdrant.'
    }
}

# ─── 9. Fichero .env ────────────────────────────────────────────────────────

Write-Step '9/11  Fichero .env'
$EnvPath = Join-Path $RepoRoot '.env'
$EnvExample = Join-Path $RepoRoot '.env.example'
if (Test-Path $EnvPath) {
    Write-Ok '.env ya existe (no se modifica)'
    $Results['.env'] = 'ok'
} elseif ($Check) {
    Write-Warn2 '.env NO existe (se crearia desde .env.example)'
    $Results['.env'] = 'falta'
} else {
    if (-not (Test-Path $EnvExample)) { throw "No se encuentra $EnvExample" }
    $content = Get-Content $EnvExample -Raw
    $vaultPath = (Join-Path $RepoRoot 'vault') -replace '\\', '/'
    $dataPath = (Join-Path $RepoRoot 'data') -replace '\\', '/'
    $content = $content -replace 'ENIGMA_VAULT_PATH=.*', "ENIGMA_VAULT_PATH=$vaultPath"
    $content = $content -replace 'ENIGMA_DATA_PATH=.*', "ENIGMA_DATA_PATH=$dataPath"
    # UTF-8 sin BOM: un BOM rompe la lectura de la primera clave por dotenv.
    $utf8NoBom = New-Object System.Text.UTF8Encoding $false
    [System.IO.File]::WriteAllText($EnvPath, $content, $utf8NoBom)
    Write-Ok '.env creado desde .env.example (rutas ajustadas a este repo)'
    Write-Warn2 'Rellena PYANNOTE_AUTH_TOKEN en .env para activar la diarizacion'
    Write-Warn2 'y acepta las condiciones del modelo en huggingface.co.'
    $Results['.env'] = 'creado'
}

# ─── 10. Qdrant ─────────────────────────────────────────────────────────────

Write-Step '10/11 Qdrant (base vectorial, contenedor Docker)'
if ($Check) {
    try {
        $qdrantCheck = Invoke-WebRequest -Uri 'http://localhost:6333/healthz' `
            -UseBasicParsing -TimeoutSec 5
        if ($qdrantCheck.StatusCode -eq 200) {
            Write-Ok 'Qdrant ya responde en :6333'
            $Results['Qdrant'] = 'ok'
        }
    } catch {
        Write-Warn2 'Qdrant no responde (se arrancaria con: docker compose up -d qdrant)'
        $Results['Qdrant'] = 'pendiente'
    }
} elseif (-not $DockerReady) {
    Write-Warn2 'Docker no esta operativo; Qdrant no se arranca. Reejecuta con Docker activo.'
    $Results['Qdrant'] = 'pendiente (Docker)'
} else {
    Push-Location $RepoRoot
    try {
        docker compose up -d qdrant
        if ($LASTEXITCODE -ne 0) { throw "docker compose up qdrant fallo (codigo $LASTEXITCODE)" }
    } finally {
        Pop-Location
    }
    Write-Ok 'Qdrant arrancado'
    $Results['Qdrant'] = 'ok'
}

# ─── 11. Verificacion ───────────────────────────────────────────────────────

Write-Step '11/11 Verificacion'

# enigma CLI
if ($Uv) {
    Push-Location $RepoRoot
    try {
        $version = & $Uv run enigma --version 2>$null
        if ($LASTEXITCODE -eq 0) {
            Write-Ok "CLI: $version"
        } else {
            Write-Warn2 'enigma --version no respondio (revisa "uv sync").'
        }
    } finally {
        Pop-Location
    }
}

# Qdrant healthz
try {
    $resp = Invoke-WebRequest -Uri 'http://localhost:6333/healthz' -UseBasicParsing -TimeoutSec 5
    if ($resp.StatusCode -eq 200) { Write-Ok 'Qdrant responde en :6333' }
} catch {
    Write-Warn2 'Qdrant no responde en :6333 (normal si Docker aun no esta listo).'
}

# Ollama
if (Test-Command 'ollama') {
    ollama list *> $null
    if ($LASTEXITCODE -eq 0) { Write-Ok 'Ollama responde' }
} else {
    Write-Warn2 'Ollama no localizable en esta sesion.'
}

# ─── Resumen ────────────────────────────────────────────────────────────────

Write-Step 'Resumen'
foreach ($key in $Results.Keys) {
    $value = $Results[$key]
    if ($value -eq 'ok' -or $value -eq 'instalado' -or $value -eq 'creado') {
        Write-Ok "${key}: $value"
    } elseif ($value -eq 'omitido') {
        Write-Host "  [-]   ${key}: $value" -ForegroundColor DarkGray
    } else {
        Write-Warn2 "${key}: $value"
    }
}

if ($Check) {
    Write-Host "`nVerificacion completada. Ejecuta el script sin -Check para instalar lo que falte." -ForegroundColor Cyan
} else {
    Write-Host "`nBootstrap completado." -ForegroundColor Green
    Write-Host 'Si se instalo software nuevo, reabre la terminal para refrescar el PATH.' -ForegroundColor Cyan
    Write-Host 'Siguiente paso: "uv run enigma ingest <audio>" para procesar tu primera llamada.' -ForegroundColor Cyan
}
