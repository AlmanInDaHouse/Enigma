#Requires -Version 5.1
<#
.SYNOPSIS
    Genera un audio sintético de la sesión de onboarding de Enigma (T-506).

.DESCRIPTION
    Lee `scripts/onboarding_script.txt` con la síntesis de voz de Windows
    (System.Speech, voz española si está disponible) y produce un `.wav`.

    Sirve para el meta-test de onboarding cuando aún no se dispone de una
    grabación real del equipo. El `.wav` está gitignored; lo reproducible es
    este script más el guion.

.PARAMETER OutputPath
    Ruta del .wav a generar. Default: data/audio/onboarding_sintetico.wav

.EXAMPLE
    .\scripts\generate_onboarding_audio.ps1
#>
[CmdletBinding()]
param(
    [string]$OutputPath
)

$ErrorActionPreference = 'Stop'
$RepoRoot = Split-Path -Parent $PSScriptRoot

$scriptText = Join-Path $RepoRoot 'scripts\onboarding_script.txt'
if (-not (Test-Path $scriptText)) {
    throw "No se encuentra el guion: $scriptText"
}

if (-not $OutputPath) {
    $OutputPath = Join-Path $RepoRoot 'data\audio\onboarding_sintetico.wav'
}
$outDir = Split-Path -Parent $OutputPath
if (-not (Test-Path $outDir)) {
    New-Item -ItemType Directory -Path $outDir -Force | Out-Null
}

Add-Type -AssemblyName System.Speech
$synth = New-Object System.Speech.Synthesis.SpeechSynthesizer

# Elegir una voz española si la hay; si no, la primera disponible.
$spanish = $synth.GetInstalledVoices() |
    Where-Object { $_.VoiceInfo.Culture.Name -like 'es-*' } |
    Select-Object -First 1
if ($spanish) {
    $synth.SelectVoice($spanish.VoiceInfo.Name)
    Write-Host "Voz: $($spanish.VoiceInfo.Name) ($($spanish.VoiceInfo.Culture.Name))"
} else {
    Write-Host "AVISO: no hay voz española instalada; se usa la voz por defecto."
}

$text = Get-Content -Path $scriptText -Raw -Encoding UTF8
$synth.SetOutputToWaveFile($OutputPath)
$synth.Speak($text)
$synth.Dispose()

$sizeKb = [math]::Round((Get-Item $OutputPath).Length / 1KB, 1)
Write-Host "Audio generado: $OutputPath ($sizeKb KB)"
