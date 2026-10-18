# CP2 runs actual Spark locally. Does NOT access Azure, Postgres, production APIs or paid models.
$ErrorActionPreference = 'Stop'
$root = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
Set-Location -LiteralPath $root
$python = Join-Path $root '.venv\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $python)) {
    throw 'Project 15 .venv missing. Run the CP1 validation script first.'
}
Write-Host 'Java runtime check (JDK 17 or 21):'
# JDKs commonly print `java -version` to stderr. Windows PowerShell 5.1 may
# treat that output as a terminating native-command error. Probe with
# Start-Process and separate files instead of cmd.exe/stderr redirection.
$javaCandidates = @()
if ($env:JAVA_HOME) {
    $javaCandidates += (Join-Path $env:JAVA_HOME 'bin\java.exe')
}
$adoptium = Join-Path $env:ProgramFiles 'Eclipse Adoptium'
if (Test-Path -LiteralPath $adoptium) {
    $javaCandidates += @(
        Get-ChildItem -LiteralPath $adoptium -Directory -ErrorAction SilentlyContinue |
            Where-Object { $_.Name -match '^jdk-(17|21)(\.|-|$)' } |
            Sort-Object Name -Descending |
            ForEach-Object { Join-Path $_.FullName 'bin\java.exe' }
    )
}
$pathJava = Get-Command java.exe -All -ErrorAction SilentlyContinue
if ($pathJava) {
    $javaCandidates += @($pathJava | ForEach-Object { $_.Source })
}
$javaCandidates = @($javaCandidates | Where-Object { $_ -and (Test-Path -LiteralPath $_ -PathType Leaf) } | Select-Object -Unique)
if ($javaCandidates.Count -eq 0) {
    throw 'Java executable not found. Install/configure JDK 17 or 21 before CP2.'
}
$probeDir = Join-Path ([System.IO.Path]::GetTempPath()) ('p15_java_' + [guid]::NewGuid().ToString('N'))
New-Item -ItemType Directory -Path $probeDir -Force | Out-Null
$selectedJava = $null
$javaVersion = $null
try {
    foreach ($candidate in $javaCandidates) {
        $outFile = Join-Path $probeDir 'java_stdout.txt'
        $errFile = Join-Path $probeDir 'java_stderr.txt'
        try {
            $probe = Start-Process -FilePath $candidate -ArgumentList '-version' -NoNewWindow -Wait -PassThru -RedirectStandardOutput $outFile -RedirectStandardError $errFile
            $details = ((Get-Content -LiteralPath $outFile -Raw -ErrorAction SilentlyContinue) + "`n" + (Get-Content -LiteralPath $errFile -Raw -ErrorAction SilentlyContinue)).Trim()
            if ($probe.ExitCode -eq 0 -and $details -match '(?i)\b(?:openjdk|java)\s+version\s+"(?:17|21)(?:\.|"|$)') {
                $selectedJava = $candidate
                $javaVersion = $details
                break
            }
            Write-Host "Java candidate not compatible: $candidate (exit code $($probe.ExitCode))"
        } catch {
            Write-Host "Java candidate failed: $candidate ($($_.Exception.Message))"
        }
    }
} finally {
    Remove-Item -LiteralPath $probeDir -Force -Recurse -ErrorAction SilentlyContinue
}
if (-not $selectedJava) {
    throw 'No working compatible JDK 17 or 21 found. CP2 dependencies were not installed.'
}
$env:JAVA_HOME = Split-Path -Parent (Split-Path -Parent $selectedJava)
$env:Path = (Join-Path $env:JAVA_HOME 'bin') + ';' + $env:Path
Write-Host "Using JAVA_HOME: $env:JAVA_HOME"
Write-Host $javaVersion
# Hadoop on native Windows needs winutils.exe + hadoop.dll to write Parquet.
# Fail before running expensive tests if they are not configured; never
# download or execute third-party native binaries implicitly.
if ($env:OS -eq 'Windows_NT') {
    $hadoopCandidates = @()
    if ($env:HADOOP_HOME) { $hadoopCandidates += $env:HADOOP_HOME }
    $hadoopCandidates += (Join-Path $env:LOCALAPPDATA 'Project15\hadoop-3.4.1')
    $hadoopCandidates += (Join-Path $env:USERPROFILE 'hadoop-3.4.1')
    $foundHadoop = $null
    foreach ($candidate in ($hadoopCandidates | Select-Object -Unique)) {
        if ((Test-Path -LiteralPath (Join-Path $candidate 'bin\winutils.exe') -PathType Leaf) -and
            (Test-Path -LiteralPath (Join-Path $candidate 'bin\hadoop.dll') -PathType Leaf)) {
            $foundHadoop = $candidate
            break
        }
    }
    if (-not $foundHadoop) {
        throw ('Missing native Hadoop 3.4 Windows helpers. Place compatible '+
            'winutils.exe and hadoop.dll in %LOCALAPPDATA%\Project15\hadoop-3.4.1\bin '+
            'or set HADOOP_HOME to their parent directory, then rerun CP2. '+
            'No binaries were downloaded automatically.')
    }
    $env:HADOOP_HOME = $foundHadoop
    $env:Path = (Join-Path $env:HADOOP_HOME 'bin') + ';' + $env:Path
    Write-Host "Using HADOOP_HOME: $env:HADOOP_HOME"
    # Spark must see Windows helper native DLLs in its JVM PATH at startup.
    & (Join-Path $env:HADOOP_HOME 'bin\winutils.exe') ls (Join-Path $env:HADOOP_HOME 'bin') | Out-Null
    if ($LASTEXITCODE -ne 0) { throw 'winutils.exe could not start; check Windows tool build compatibility.' }
}
Write-Host 'Installing the CP2-only dependencies...'
& $python -m pip install -r (Join-Path $root 'requirements-cp2.txt')
if ($LASTEXITCODE -ne 0) { throw 'CP2 dependency installation failed' }
$env:PYTHONPATH = Join-Path $root 'src'
$env:PYSPARK_PYTHON = $python
$env:PYSPARK_DRIVER_PYTHON = $python
$env:SPARK_LOCAL_IP = '127.0.0.1'
Write-Host 'Running CP1 + CP2 tests (Spark tests included)...'
& $python -m pytest -o addopts='' -q
if ($LASTEXITCODE -ne 0) { throw 'CP2 tests failed; workflow demo not run' }
$stamp = Get-Date -Format 'yyyyMMdd_HHmmss'
$sourceId = 'cp2_source_' + $stamp
$targetId = 'cp2_platform_' + $stamp
$repeatId = 'cp2_repeat_' + $stamp
Write-Host 'Running CP2 synthetic ingestion and Spark platform...'
& $python -m enterprise_automation.cp1_demo --root "$root" --run-id $sourceId
if ($LASTEXITCODE -ne 0) { throw 'CP2 source-ingestion setup failed' }
& $python -m enterprise_automation.cp2_demo --root "$root" --source-run-id $sourceId --run-id $targetId --trigger-mode scheduled --trigger-id $targetId --load-mode incremental
if ($LASTEXITCODE -ne 0) { throw 'CP2 local Spark platform failed' }
Write-Host 'Running incremental replay with new run ID: unchanged inputs should produce 0 new ERP rows...'
& $python -m enterprise_automation.cp2_demo --root "$root" --source-run-id $sourceId --run-id $repeatId --trigger-mode manual --load-mode incremental
if ($LASTEXITCODE -ne 0) { throw 'CP2 incremental replay check failed' }
Write-Host "CP2 completed; source: $sourceId; platform: $targetId; replay: $repeatId"
Write-Host "Evidence: data\processed\$targetId\cp2_manifest.json"
