param(
  [string]$VoiceName = "Microsoft Zira Desktop",
  [int]$Rate = -6,
  [string]$OutputDir = "",
  [switch]$NoRadioFilter
)

$ErrorActionPreference = "Stop"

$extensionDir = Resolve-Path (Join-Path $PSScriptRoot "..")
$promptModule = Join-Path $extensionDir "voice_prompts.js"

if (-not $OutputDir) {
  $OutputDir = Join-Path $extensionDir "assets\voice_prompts"
}

$promptJson = node -e "const prompts = require(process.argv[1]); console.log(JSON.stringify(prompts.PROMPT_BANK.map(({id,event,filename,text}) => ({id,event,filename,text}))));" $promptModule
$prompts = $promptJson | ConvertFrom-Json

New-Item -ItemType Directory -Force -Path $OutputDir | Out-Null

$ffmpeg = Get-Command ffmpeg -ErrorAction SilentlyContinue
$useRadioFilter = (-not $NoRadioFilter) -and $null -ne $ffmpeg
$tempDir = Join-Path ([System.IO.Path]::GetTempPath()) ("dopamaxx_voice_prompts_" + [System.Guid]::NewGuid().ToString("N"))
New-Item -ItemType Directory -Force -Path $tempDir | Out-Null

Add-Type -AssemblyName System.Speech
$speaker = New-Object System.Speech.Synthesis.SpeechSynthesizer
$speaker.Rate = $Rate
$speaker.Volume = 100

try {
  $speaker.SelectVoice($VoiceName)
} catch {
  Write-Warning "Voice '$VoiceName' was not found. Falling back to '$($speaker.Voice.Name)'."
}

try {
  foreach ($prompt in $prompts) {
    $path = Join-Path $OutputDir $prompt.filename
    $rawPath = Join-Path $tempDir $prompt.filename
    $speaker.SetOutputToWaveFile($rawPath)
    $speaker.Speak($prompt.text)
    $speaker.SetOutputToNull()

    if ($useRadioFilter) {
      $filter = "[0:a]aresample=22050,asetrate=20727,aresample=22050,highpass=f=420,lowpass=f=2450,acompressor=threshold=-30dB:ratio=8:attack=4:release=220,acrusher=bits=8:mode=log:mix=0.42,aecho=0.75:0.68:95:0.10,volume=1.65[v];anoisesrc=color=white:amplitude=0.035[static];anoisesrc=color=brown:amplitude=0.018[rumble];sine=frequency=1030:sample_rate=22050:duration=3600,volume=0.018[carrier];sine=frequency=72:sample_rate=22050:duration=3600,volume=0.008[hum];[v][static][rumble][carrier][hum]amix=inputs=5:duration=first:weights='1 0.33 0.20 0.18 0.12',alimiter=limit=0.82,volume=1.08"
      & $ffmpeg.Source -hide_banner -loglevel error -y -i $rawPath -filter_complex $filter -ar 22050 -ac 1 $path
      if ($LASTEXITCODE -ne 0) {
        throw "ffmpeg failed while rendering $($prompt.filename)"
      }
    } else {
      Copy-Item -Force -Path $rawPath -Destination $path
    }

    Write-Output $path
  }
} finally {
  if ($speaker) {
    $speaker.Dispose()
  }
  Remove-Item -Recurse -Force -Path $tempDir -ErrorAction SilentlyContinue
}
