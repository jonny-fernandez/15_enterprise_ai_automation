# Setup existing community-provided Hadoop 3.4.1 Windows native assets.
# NEVER download/execute code here; extract only the two explicit ZIP entries
# after validating the SHA-256 of the community release archive.
param([Parameter(Mandatory=$true)][string]$NativeZip)
$ErrorActionPreference = 'Stop'
$expected = 'AA8098A433E6D63B865074468AA2DA1AA9329EF33C9E9AF799037F382CE50B82'
if (-not (Test-Path -LiteralPath $NativeZip -PathType Leaf)) { throw 'Hadoop ZIP missing' }
$hash = (Get-FileHash -LiteralPath $NativeZip -Algorithm SHA256).Hash
if ($hash -ne $expected) { throw 'Unexpected ZIP checksum; refusing extraction' }
Add-Type -AssemblyName System.IO.Compression.FileSystem
$zip = [System.IO.Compression.ZipFile]::OpenRead((Resolve-Path -LiteralPath $NativeZip).Path)
$temp = Join-Path $env:TEMP ('project15_hadoop_' + [guid]::NewGuid().ToString('N'))
$destination = Join-Path $env:LOCALAPPDATA 'Project15\hadoop-3.4.1\bin'
New-Item -ItemType Directory -Force -Path $temp | Out-Null
try {
    foreach ($filename in @('winutils.exe','hadoop.dll')) {
        $matches = @($zip.Entries | Where-Object {
            ($_.FullName -replace '\\','/') -eq "hadoop-3.4.1/bin/$filename"
        })
        if ($matches.Count -ne 1 -or $matches[0].Length -le 0) {
            throw "Missing or ambiguous Hadoop native file: $filename"
        }
        [System.IO.Compression.ZipFileExtensions]::ExtractToFile(
            $matches[0], (Join-Path $temp $filename), $true)
    }
    New-Item -ItemType Directory -Force -Path $destination | Out-Null
    foreach ($filename in @('winutils.exe','hadoop.dll')) {
        Copy-Item -LiteralPath (Join-Path $temp $filename) -Destination $destination -Force
    }
    Write-Host "Native Hadoop helpers ready: $destination"
} finally {
    $zip.Dispose()
    Remove-Item -LiteralPath $temp -Recurse -Force -ErrorAction SilentlyContinue
}
