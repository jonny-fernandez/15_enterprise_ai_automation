# CP4 prepublication Windows gate. No downloads, Git initialization, cloud writes or publication.
$ErrorActionPreference='Stop'
$root=(Resolve-Path (Join-Path $PSScriptRoot '..')).Path
Set-Location -LiteralPath $root
$python=Join-Path $root '.venv\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $python)) { throw 'Validated CP3 Python .venv not found.' }
$jdkPaths=@()
if ($env:JAVA_HOME) { $jdkPaths+= $env:JAVA_HOME }
$adoptium=Join-Path $env:ProgramFiles 'Eclipse Adoptium'
if (Test-Path -LiteralPath $adoptium) {
    $jdkPaths+= @(Get-ChildItem -LiteralPath $adoptium -Directory -ErrorAction SilentlyContinue |
        Where-Object { $_.Name -match '^jdk-(17|21)(\.|-|$)' } |
        Sort-Object Name -Descending | ForEach-Object {$_.FullName})
}
$jdk=$jdkPaths | Where-Object {Test-Path -LiteralPath (Join-Path $_ 'bin\java.exe')} | Select-Object -First 1
if (-not $jdk) {throw 'Existing tested JDK 17/21 not found.'}
$env:JAVA_HOME=$jdk
$env:Path=(Join-Path $jdk 'bin')+';'+$env:Path
$hadoop=@($env:HADOOP_HOME, (Join-Path $env:LOCALAPPDATA 'Project15\hadoop-3.4.1')) |
    Where-Object { $_ -and (Test-Path -LiteralPath (Join-Path $_ 'bin\winutils.exe')) -and
                        (Test-Path -LiteralPath (Join-Path $_ 'bin\hadoop.dll')) } | Select-Object -First 1
if (-not $hadoop) {throw 'Existing CP2 Hadoop helpers are missing.'}
$env:HADOOP_HOME=$hadoop
$env:Path=(Join-Path $hadoop 'bin')+';'+$env:Path
$env:PYTHONPATH=Join-Path $root 'src'
$env:PYSPARK_PYTHON=$python
$env:PYSPARK_DRIVER_PYTHON=$python
$env:SPARK_LOCAL_IP='127.0.0.1'
Write-Host "CP4: using $jdk and $hadoop"
$xml=Join-Path $env:TEMP ('p15_cp4_'+[guid]::NewGuid().ToString('N')+'.xml')
try {
    & $python -m pytest -o addopts='' -q --junitxml $xml
    if ($LASTEXITCODE -ne 0) {throw 'CP4 Windows test suite failed.'}
    [xml]$data=Get-Content -LiteralPath $xml -Raw
    $suite=$data.testsuites.testsuite
    if (([int]$suite.failures+[int]$suite.errors) -ne 0 -or [int]$suite.skipped -ne 0 -or [int]$suite.tests -lt 139) {
        throw "Incomplete CP4 gate: tests=$($suite.tests) failures=$($suite.failures) errors=$($suite.errors) skipped=$($suite.skipped)"
    }
    Write-Host "CP4 Windows test gate passed: $($suite.tests) tests, zero failures, zero skips."
} finally {
    Remove-Item -LiteralPath $xml -Force -ErrorAction SilentlyContinue
}
Write-Host 'Running read-only release-path and credential pattern audit...'
& $python scripts/audit_cp4.py --root $root --output artifacts/cp4_repository_audit.json
if ($LASTEXITCODE -ne 0) { throw 'CP4 security audit found a blocking issue.' }
Write-Host 'CP4 local prepublication checks completed; GitHub CI, Azure scope, screenshot handoff and user approval still pending.'
