$ErrorActionPreference = "Stop"

Write-Host "MEHDORA Qt query bootstrap V4"

$sourceRoot = (Get-Location).Path
$toolRoot = Join-Path $sourceRoot "_mehdora_tools"
$helper = Join-Path $toolRoot "qtpaths-mehdora.exe"
$source = Join-Path $toolRoot "qtpaths-mehdora.c"
$gcc = "C:\mingw64\bin\gcc.exe"

New-Item -ItemType Directory -Path $toolRoot -Force | Out-Null

if (-not (Test-Path $gcc)) {
    throw "MinGW gcc was not found at $gcc"
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
    char prefix[32768];
    DWORD n = GetEnvironmentVariableA("MEHDORA_QT_PREFIX", prefix, sizeof(prefix));
    if (!n || n >= sizeof(prefix)) {
        fputs("MEHDORA_QT_PREFIX is not set\n", stderr);
        return 2;
    }
    slash(prefix);

    if (argc >= 3 && (!strcmp(argv[1], "--query") || !strcmp(argv[1], "-query"))) {
        const char *key = argv[2];
        if (!strcmp(key, "QT_INSTALL_HEADERS")) printf("%s/include\n", prefix);
        else if (!strcmp(key, "QT_INSTALL_LIBS")) printf("%s/lib\n", prefix);
        else if (!strcmp(key, "QT_INSTALL_BINS") || !strcmp(key, "QT_INSTALL_LIBEXECS") ||
                 !strcmp(key, "QT_HOST_BINS") || !strcmp(key, "QT_HOST_LIBEXECS"))
            printf("%s/bin\n", prefix);
        else if (!strcmp(key, "QT_INSTALL_PLUGINS")) printf("%s/plugins\n", prefix);
        else if (!strcmp(key, "QT_INSTALL_QML")) printf("%s/qml\n", prefix);
        else if (!strcmp(key, "QT_INSTALL_TRANSLATIONS")) printf("%s/translations\n", prefix);
        else if (!strcmp(key, "QT_INSTALL_DOCS")) printf("%s/doc\n", prefix);
        else if (!strcmp(key, "QT_INSTALL_EXAMPLES") || !strcmp(key, "QT_INSTALL_DEMOS"))
            printf("%s/examples\n", prefix);
        else if (!strcmp(key, "QT_INSTALL_TESTS")) printf("%s/tests\n", prefix);
        else printf("%s\n", prefix);
        return 0;
    }
    if (argc == 2 && !strcmp(argv[1], "--qt-version")) {
        puts("6.0.0");
        return 0;
    }
    fputs("Unsupported qtpaths arguments\n", stderr);
    return 1;
}
'@ | Set-Content -Path $source -Encoding ascii

& $gcc -Os -static -s $source -o $helper
if ($LASTEXITCODE -ne 0 -or -not (Test-Path $helper)) {
    throw "Failed to compile MEHDORA qtpaths helper."
}

$env:MEHDORA_QT_PREFIX = (Join-Path $sourceRoot "_install")
& $helper --query QT_INSTALL_PREFIX
if ($LASTEXITCODE -ne 0) {
    throw "MEHDORA qtpaths helper test failed."
}

Write-Output $helper
