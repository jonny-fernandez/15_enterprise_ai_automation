# CP3 Windows validation: run all CP1-CP3 tests, including *real* Spark.
# No installs, cloud requests, credential use or production connections.
$ErrorActionPreference = 'Stop'
$root = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
Set-Location -LiteralPath $root
$python = Join-Path $root '.venv\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $python)) { throw 'Existing Project 15 .venv not found. Run validated CP2 first.' }

$jdkPaths = @()
if ($env:JAVA_HOME) { $jdkPaths += $env:JAVA_HOME }
$adoptium = Join-Path $env:ProgramFiles 'Eclipse Adoptium'
if (Test-Path -LiteralPath $adoptium) {
    $jdkPaths += @(Get-ChildItem $adoptium -Directory -ErrorAction SilentlyContinue |
        Where-Object {$_.Name -match '^jdk-(17|21)(\.|-|$)'} | Sort-Object Name -Descending |
        ForEach-Object {$_.FullName})
}
$jdk = $jdkPaths | Where-Object {Test-Path -LiteralPath (Join-Path $_ 'bin\java.exe')} | Select-Object -First 1
if (-not $jdk) { throw 'A working JDK 17 or 21 is required for the real Spark tests.' }
$env:JAVA_HOME = $jdk
$env:Path = (Join-Path $jdk 'bin') + ';' + $env:Path

$hadoop = @($env:HADOOP_HOME, (Join-Path $env:LOCALAPPDATA 'Project15\hadoop-3.4.1')) |
    Where-Object {$_ -and (Test-Path -LiteralPath (Join-Path $_ 'bin\winutils.exe')) -and
        (Test-Path -LiteralPath (Join-Path $_ 'bin\hadoop.dll'))} | Select-Object -First 1
if (-not $hadoop) { throw 'Missing existing Hadoop native helpers. CP2 must pass first.' }
$env:HADOOP_HOME = $hadoop
$env:Path = (Join-Path $hadoop 'bin') + ';' + $env:Path
$env:PYTHONPATH = Join-Path $root 'src'
$env:PYSPARK_PYTHON = $python
$env:PYSPARK_DRIVER_PYTHON = $python
$env:SPARK_LOCAL_IP = '127.0.0.1'

Write-Host "Using Java: $jdk"
Write-Host "Using Hadoop: $hadoop"
Write-Host 'Running CP1+CP2+CP3 tests (real Spark required, zero skips)...'
$xml = Join-Path $env:TEMP ('project15_cp3_tests_' + [guid]::NewGuid().ToString('N') + '.xml')
try {
    & $python -m pytest -o addopts='' -q --junitxml "$xml"
    if ($LASTEXITCODE -ne 0) { throw 'Project 15 tests failed.' }
    [xml]$report = Get-Content -LiteralPath $xml -Raw
    $suite = $report.testsuites.testsuite
    $failures = [int]$suite.failures + [int]$suite.errors
    $skipped = [int]$suite.skipped
    $count = [int]$suite.tests
    if ($failures -ne 0 -or $skipped -ne 0 -or $count -lt 120) {
        throw "Incomplete CP3 test gate: tests=$count failures=$failures skipped=$skipped"
    }
    Write-Host "CP3 test gate passed: $count tests, zero failures, zero skips."
} finally {
    Remove-Item -LiteralPath $xml -Force -ErrorAction SilentlyContinue
}
$runId = 'cp3_evaluation_' + (Get-Date -Format 'yyyyMMdd_HHmmss')
Write-Host "Running locked synthetic evaluation: $runId"
& $python -m enterprise_automation.cp3_demo --root "$root" --run-id "$runId"
if ($LASTEXITCODE -ne 0) { throw 'CP3 evaluation failed.' }
Write-Host "CP3 completed; evidence: artifacts\${runId}_cp3_manifest.json"
