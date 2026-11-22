# Builds the Android app: dist\BiggestHighway.apk (and the Play Store bundle in build-android\dist).
#
#   powershell -ExecutionPolicy Bypass -File android\build_apk.ps1
#
# Needs Python 3.13 and Java 17+ (for bundletool). Everything else is downloaded
# into build-android\ (git-ignored) and checked against known SHA-256 hashes.
# The APK is signed with a key kept outside the repo, in %USERPROFILE%\.android\.
# Keep that file: Android only installs an update over an app signed with the same key.
param([switch]$Clean)
# Not 'Stop': Windows PowerShell 5.1 would treat warnings that pip, keytool or the
# build print on stderr as fatal. Each step checks its exit code instead.
$ErrorActionPreference = 'Continue'
trap { Write-Host "ERROR: $_" -ForegroundColor Red; exit 1 }
$root = Split-Path -Parent $PSScriptRoot
Set-Location $root

$work = Join-Path $root 'build-android'
$wheels = Join-Path $work 'wheels'
New-Item -ItemType Directory -Force $wheels | Out-Null
if ($Clean) { Remove-Item -Recurse -Force (Join-Path $work 'build'), (Join-Path $work 'dist') -ErrorAction SilentlyContinue }

function Get-Checked($url, $path, $sha) {
    if (-not (Test-Path $path)) {
        Write-Host "Downloading $(Split-Path $path -Leaf)..."
        Invoke-WebRequest -UseBasicParsing $url -OutFile "$path.part" -ErrorAction Stop
        Move-Item -Force "$path.part" $path -ErrorAction Stop
    }
    $got = (Get-FileHash $path -Algorithm SHA256).Hash.ToLower()
    if ($got -ne $sha) {
        Remove-Item $path
        throw "$(Split-Path $path -Leaf) does not match its known SHA-256 (got $got). It was deleted; if the file was updated on purpose, put its new hash in android\build_apk.ps1."
    }
}

# --- 1. Panda3D 1.11 (the first version that can build Android apps) --------------
$commit = '418d041252ab55850258012399bc63938552f65b'
$hostWhl = 'panda3d-1.11.0.dev3823-cp313-cp313-win_amd64.whl'
Get-Checked "https://buildbot.panda3d.org/downloads/$commit/$hostWhl" (Join-Path $work $hostWhl) `
    '4144044bdd061a97b7b9f32cb622b6b762155b25a837f34cfbf3b9abcef7244a'
$android = @{
    'arm64'  = '7c72074c16224c1a9f3de8bdca10388ef5d573ae9b8bf368588d4bea1319fc03'
    'armv7a' = 'a414a0056d8ca03417a52fda36f0211d95485ade90bc2abc92af9c2d24e94d3b'
    'x86_64' = '98c76ea46bc44284896f4c042f0d1e7fb3b2de1ab2d921629dea3f7b4aa88d0a'
}
foreach ($abi in $android.Keys) {
    $name = "panda3d-1.11.0-cp313-cp313-android_$abi.whl"
    Get-Checked "https://rdb.name/$name" (Join-Path $wheels $name) $android[$abi]
}

# --- 2. A separate Python 3.13 environment for the Android build ---------------------
$py = Join-Path $root '.venv-android\Scripts\python.exe'
if (-not (Test-Path $py)) {
    Write-Host 'Creating .venv-android (Python 3.13)...'
    & py -3.13 -m venv .venv-android
    if ($LASTEXITCODE) { throw 'Could not create a Python 3.13 environment (is Python 3.13 installed?)' }
}
& $py -m pip install -q --disable-pip-version-check (Join-Path $work $hostWhl) setuptools protobuf screeninfo==0.8.1 pyperclip==1.11.0
if ($LASTEXITCODE) { throw 'pip install failed' }
# --no-deps: Ursina would otherwise pull in Panda3D 1.10 and Pillow (which has no Android version)
& $py -m pip install -q --disable-pip-version-check --no-deps ursina==8.3.0 panda3d-gltf==1.3.0
if ($LASTEXITCODE) { throw 'pip install failed' }

# --- 3. bundletool (turns the .aab bundle into an APK) ------------------------------
$bt = Join-Path $work 'bundletool-all-1.18.3.jar'
Get-Checked 'https://github.com/google/bundletool/releases/download/1.18.3/bundletool-all-1.18.3.jar' $bt `
    'a099cfa1543f55593bc2ed16a70a7c67fe54b1747bb7301f37fdfd6d91028e29'
$java = (Get-Command java -ErrorAction SilentlyContinue).Source
if (-not $java) { throw 'Java 17 or newer is needed (for bundletool and keytool).' }
$keytool = (Get-Command keytool -ErrorAction SilentlyContinue).Source
if (-not $keytool) {
    $keytool = Get-ChildItem 'C:\Program Files\Java', 'C:\Program Files\Eclipse Adoptium', 'C:\Program Files\Microsoft' `
        -Filter keytool.exe -Recurse -ErrorAction SilentlyContinue | Select-Object -Last 1 -ExpandProperty FullName
}
if (-not $keytool) { throw 'keytool (part of the Java JDK) was not found.' }

# --- 4. Signing key (made once, kept out of the repo) -------------------------------
$ks = if ($env:BH_KEYSTORE) { $env:BH_KEYSTORE } else { Join-Path $env:USERPROFILE '.android\biggest-highway.keystore' }
$ksPass = if ($env:BH_KEYSTORE_PASS) { $env:BH_KEYSTORE_PASS } else { 'android' }
$alias = 'biggesthighway'
if (-not (Test-Path $ks)) {
    Write-Host "Creating a signing key: $ks"
    New-Item -ItemType Directory -Force (Split-Path $ks) | Out-Null
    & $keytool -genkeypair -noprompt -storetype pkcs12 -keystore $ks -alias $alias -keyalg RSA -keysize 2048 -validity 10000 `
        -storepass $ksPass -keypass $ksPass -dname 'CN=Biggest Highway'
    if ($LASTEXITCODE) { throw 'keytool failed' }
}

# --- 5. Build the bundle (.aab) ------------------------------------------------------
Write-Host 'Building the Android bundle (takes a few minutes)...'
$log = Join-Path $work 'build.log'
& $py setup.py bdist_apps 2>&1 | ForEach-Object { "$_" } | Out-File -Encoding utf8 $log
if ($LASTEXITCODE) { Get-Content $log -Tail 30; throw "build failed, see $log" }
$aab = Get-ChildItem (Join-Path $work 'dist') -Filter *.aab | Sort-Object LastWriteTime | Select-Object -Last 1
if (-not $aab) { throw "no .aab was made, see $log" }

# --- 6. Bundle -> one universal, signed APK ------------------------------------------
$apks = Join-Path $work 'BiggestHighway.apks'
& $java -jar $bt build-apks --bundle $aab.FullName --output $apks --mode=universal --overwrite `
    --ks $ks --ks-pass "pass:$ksPass" --ks-key-alias $alias --key-pass "pass:$ksPass"
if ($LASTEXITCODE) { throw 'bundletool build-apks failed' }
$unz = Join-Path $work 'apks'
Remove-Item -Recurse -Force $unz -ErrorAction SilentlyContinue
Add-Type -AssemblyName System.IO.Compression.FileSystem
[System.IO.Compression.ZipFile]::ExtractToDirectory($apks, $unz)   # .apks is a zip
New-Item -ItemType Directory -Force (Join-Path $root 'dist') | Out-Null
$apk = Join-Path $root 'dist\BiggestHighway.apk'
Copy-Item (Join-Path $unz 'universal.apk') $apk -Force -ErrorAction Stop
$mb = (Get-Item $apk).Length / 1MB
Write-Host ("Done: {0}  ({1:N1} MB)" -f $apk, $mb)
Write-Host ('SHA-256: ' + (Get-FileHash $apk).Hash)
