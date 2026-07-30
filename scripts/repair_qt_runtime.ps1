$ErrorActionPreference = "Stop"

Write-Host "MEHDORA Qt runtime repair V3"

$installRoot = (Resolve-Path "_install").Path
$qtBin = Join-Path $installRoot "bin"
$qtpaths = Join-Path $qtBin "qtpaths.exe"
$objdump = "C:\mingw64\bin\objdump.exe"

if (-not (Test-Path $qtpaths)) {
    throw "qtpaths.exe was not found at: $qtpaths"
}

if (-not (Test-Path $objdump)) {
    throw "objdump.exe was not found at: $objdump"
}

$env:PATH = "$qtBin;C:\mingw64\bin;$env:PATH"

Write-Host "Indexing Qt and MinGW runtime DLL files..."
$dllIndex = @{}

foreach ($root in @($installRoot, "C:\mingw64\bin")) {
    if (-not (Test-Path $root)) {
        continue
    }

    Get-ChildItem $root -Filter "*.dll" -File -Recurse -ErrorAction SilentlyContinue |
        ForEach-Object {
            $key = $_.Name.ToLowerInvariant()
            if (-not $dllIndex.ContainsKey($key)) {
                $dllIndex[$key] = $_.FullName
            }
        }
}

$systemDlls = @(
    "advapi32.dll", "bcrypt.dll", "comdlg32.dll", "crypt32.dll",
    "dwmapi.dll", "gdi32.dll", "imm32.dll", "kernel32.dll",
    "mpr.dll", "netapi32.dll", "ntdll.dll", "ole32.dll",
    "oleaut32.dll", "shell32.dll", "user32.dll", "userenv.dll",
    "uxtheme.dll", "version.dll", "winmm.dll", "winspool.drv",
    "ws2_32.dll"
)

$systemSet = @{}
foreach ($name in $systemDlls) {
    $systemSet[$name] = $true
}

function Get-ImportedDlls([string]$binary) {
    $result = & $objdump -p $binary 2>$null
    if ($LASTEXITCODE -ne 0) {
        return @()
    }

    return @(
        $result |
            Select-String -Pattern "DLL Name:\s*(.+)$" |
            ForEach-Object { $_.Matches[0].Groups[1].Value.Trim() } |
            Sort-Object -Unique
    )
}

$queue = [System.Collections.Generic.Queue[string]]::new()
$visited = @{}
$unresolved = @{}
$queue.Enqueue($qtpaths)

while ($queue.Count -gt 0) {
    $binary = $queue.Dequeue()
    $binaryKey = $binary.ToLowerInvariant()

    if ($visited.ContainsKey($binaryKey)) {
        continue
    }
    $visited[$binaryKey] = $true

    foreach ($dependency in (Get-ImportedDlls $binary)) {
        $name = $dependency.ToLowerInvariant()

        if ($name.StartsWith("api-ms-win-") -or
            $name.StartsWith("ext-ms-win-") -or
            $systemSet.ContainsKey($name)) {
            continue
        }

        $destination = Join-Path $qtBin $dependency
        if (-not (Test-Path $destination)) {
            if ($dllIndex.ContainsKey($name)) {
                Write-Host "Copying runtime dependency: $dependency"
                Copy-Item $dllIndex[$name] $destination -Force
            }
            else {
                $systemCandidate = Join-Path $env:WINDIR "System32\$dependency"
                if (-not (Test-Path $systemCandidate)) {
                    $unresolved[$name] = $true
                }
            }
        }

        if (Test-Path $destination) {
            $queue.Enqueue($destination)
        }
    }
}

if ($unresolved.Count -gt 0) {
    Write-Warning ("Unresolved non-system DLLs: " + (($unresolved.Keys | Sort-Object) -join ", "))
}

Write-Host "Testing qtpaths.exe..."
& $qtpaths --query QT_INSTALL_PREFIX
if ($LASTEXITCODE -ne 0) {
    Write-Host "Direct imports of qtpaths.exe:"
    Get-ImportedDlls $qtpaths | ForEach-Object { Write-Host " - $_" }

    $qtCore = Join-Path $qtBin "Qt6Core.dll"
    if (Test-Path $qtCore) {
        Write-Host "Direct imports of Qt6Core.dll:"
        Get-ImportedDlls $qtCore | ForEach-Object { Write-Host " - $_" }
    }

    Write-Warning "The downloaded qtpaths.exe is incompatible with this runner."
    Write-Host "Building a dependency-free qtpaths compatibility helper..."

    $qtpathsSource = Join-Path $env:RUNNER_TEMP "mehdora_qtpaths.c"
    $qtpathsBackup = Join-Path $qtBin "qtpaths-original.exe"
    $gcc = "C:\mingw64\bin\gcc.exe"

    if (-not (Test-Path $gcc)) {
        throw "MinGW gcc was not found; cannot build the qtpaths compatibility helper."
    }

    @'
#include <windows.h>
#include <stdio.h>
#include <string.h>

static void slash(char *s) {
    while (*s) {
        if (*s == '\\') *s = '/';
        ++s;
    }
}

int main(int argc, char **argv) {
    char exe[MAX_PATH];
    char prefix[MAX_PATH];
    DWORD n = GetModuleFileNameA(NULL, exe, MAX_PATH);
    if (!n || n >= MAX_PATH) return 2;
    strcpy(prefix, exe);
    char *p = strrchr(prefix, '\\');
    if (p) *p = 0;
    p = strrchr(prefix, '\\');
    if (p) *p = 0;
    slash(prefix);

    if (argc >= 3 && (!strcmp(argv[1], "--query") || !strcmp(argv[1], "-query"))) {
        const char *key = argv[2];
        if (!strcmp(key, "QT_INSTALL_PREFIX") || !strcmp(key, "QT_HOST_PREFIX") ||
            !strcmp(key, "QT_INSTALL_DATA") || !strcmp(key, "QT_INSTALL_ARCHDATA") ||
            !strcmp(key, "QT_INSTALL_CONFIGURATION")) {
            printf("%s\n", prefix);
        } else if (!strcmp(key, "QT_INSTALL_HEADERS")) {
            printf("%s/include\n", prefix);
        } else if (!strcmp(key, "QT_INSTALL_LIBS")) {
            printf("%s/lib\n", prefix);
        } else if (!strcmp(key, "QT_INSTALL_BINS") || !strcmp(key, "QT_INSTALL_LIBEXECS") ||
                   !strcmp(key, "QT_HOST_BINS") || !strcmp(key, "QT_HOST_LIBEXECS")) {
            printf("%s/bin\n", prefix);
        } else if (!strcmp(key, "QT_INSTALL_PLUGINS")) {
            printf("%s/plugins\n", prefix);
        } else if (!strcmp(key, "QT_INSTALL_QML")) {
            printf("%s/qml\n", prefix);
        } else if (!strcmp(key, "QT_INSTALL_TRANSLATIONS")) {
            printf("%s/translations\n", prefix);
        } else if (!strcmp(key, "QT_INSTALL_DOCS")) {
            printf("%s/doc\n", prefix);
        } else if (!strcmp(key, "QT_INSTALL_EXAMPLES") || !strcmp(key, "QT_INSTALL_DEMOS")) {
            printf("%s/examples\n", prefix);
        } else if (!strcmp(key, "QT_INSTALL_TESTS")) {
            printf("%s/tests\n", prefix);
        } else {
            printf("%s\n", prefix);
        }
        return 0;
    }

    if (argc == 2 && !strcmp(argv[1], "--qt-version")) {
        puts("6.0.0");
        return 0;
    }

    fprintf(stderr, "MEHDORA qtpaths compatibility helper: unsupported arguments\n");
    return 1;
}
'@ | Set-Content -Path $qtpathsSource -Encoding ascii

    Move-Item $qtpaths $qtpathsBackup -Force
    & $gcc -Os -static -s $qtpathsSource -o $qtpaths
    if ($LASTEXITCODE -ne 0 -or -not (Test-Path $qtpaths)) {
        throw "Failed to compile the qtpaths compatibility helper."
    }

    Write-Host "Testing the compatibility helper..."
    & $qtpaths --query QT_INSTALL_PREFIX
    if ($LASTEXITCODE -ne 0) {
        throw "The qtpaths compatibility helper could not start."
    }
}

Write-Host "Qt runtime is ready."
