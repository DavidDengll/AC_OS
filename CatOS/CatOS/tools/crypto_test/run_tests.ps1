# tools/crypto_test/run_tests.ps1
#
# 一条命令重建全部向量并运行密码学自测:
#   python 生成 SHA-256/HMAC/PRF 与 AES-GCM 向量
#   .NET    生成 SHA-1/AES-ECB/CBC/CTR 与 RSA 向量
#   gcc     编译 test.c (直接 include 内核源码) 并运行
#
# 用法: powershell -File run_tests.ps1

$ErrorActionPreference = "Stop"
Set-Location -LiteralPath $PSScriptRoot

Write-Host "[1/5] python: SHA-256 / HMAC / PRF"
python gen_vectors.py expected.h
if ($LASTEXITCODE -ne 0) { throw "gen_vectors.py failed" }

Write-Host "[2/5] python: AES-128-GCM (FIPS-197 + NIST self-checked)"
python gen_gcm_vectors.py expected_gcm.h
if ($LASTEXITCODE -ne 0) { throw "gen_gcm_vectors.py failed" }

Write-Host "[3/5] .NET: SHA-1 / HMAC-SHA1 / AES-ECB / CBC / CTR"
powershell -NoProfile -ExecutionPolicy Bypass -File gen_vectors_net.ps1 -OutFile expected_net.h
if ($LASTEXITCODE -ne 0) { throw "gen_vectors_net.ps1 failed" }

Write-Host "[4/5] .NET: RSA-2048 (modpow / signature / PKCS#1 v1.5)"
powershell -NoProfile -ExecutionPolicy Bypass -File gen_rsa_vectors.ps1 -OutFile expected_rsa.h
if ($LASTEXITCODE -ne 0) { throw "gen_rsa_vectors.ps1 failed" }

Write-Host "[5/5] build and run"
gcc -DBR_HOST_BUILD -I shim -I ../../include -O2 -Wall -o crypto_test.exe test.c
if ($LASTEXITCODE -ne 0) { throw "gcc failed" }
.\crypto_test.exe
exit $LASTEXITCODE
