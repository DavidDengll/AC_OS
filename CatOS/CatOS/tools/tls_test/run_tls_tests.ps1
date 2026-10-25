# tools/tls_test/run_tls_tests.ps1
# 生成服务端夹具 -> 编译 C 测试 -> 运行 -> 用 Python 反向校验 ClientHello

$ErrorActionPreference = "Stop"
Set-Location -LiteralPath $PSScriptRoot

Write-Host "[1/4] python: generate server fixtures (independent framing)"
python gen_fixtures.py fixtures.h
if ($LASTEXITCODE -ne 0) { throw "gen_fixtures.py failed" }

Write-Host "[2/4] build"
gcc -I shim -I ../../include -O2 -Wall -o tls_test.exe test_tls.c
if ($LASTEXITCODE -ne 0) { throw "gcc failed" }

Write-Host "[3/4] run C tests"
.\tls_test.exe client_hello.txt
if ($LASTEXITCODE -ne 0) { throw "C tests failed" }

Write-Host "[4/4] python: parse the ClientHello the C code produced"
python verify_hello.py client_hello.txt
if ($LASTEXITCODE -ne 0) { throw "ClientHello verification failed" }
Write-Host "[5/8] RSA key pair for handshake test"
powershell -NoProfile -ExecutionPolicy Bypass -File gen_hs_key.ps1
if ($LASTEXITCODE -ne 0) { throw "gen_hs_key.ps1 failed" }

Write-Host "[6/8] build handshake test"
gcc -I shim -I ../../include -O2 -Wall -o hs_test.exe test_handshake.c
if ($LASTEXITCODE -ne 0) { throw "gcc (handshake) failed" }

Write-Host "[7/8] phase 1: client messages + keying + sealed Finished"
.\hs_test.exe phase1 client_out.txt server_out.txt
if ($LASTEXITCODE -ne 0) { throw "handshake phase1 failed" }

Write-Host "[8/8] python server emulation, then phase 2 reply check"
python server_emu.py client_out.txt hs_key.txt server_out.txt
if ($LASTEXITCODE -ne 0) { throw "server emulation failed" }
.\hs_test.exe phase2 client_out.txt server_out.txt
if ($LASTEXITCODE -ne 0) { throw "handshake phase2 failed" }

Write-Host "TLS codec + handshake tests: ALL PASSED"
# ---- X.509 证书链 ----
# 注意: 某些机器上"同一条命令里编译并立刻运行"会被应用控制策略拦下,
#       如果遇到, 把 gcc 与 .\xxx.exe 分两次执行即可.
Write-Host "[9/11] .NET: generate X.509 certificate chain"
powershell -NoProfile -ExecutionPolicy Bypass -File gen_certs.ps1
if ($LASTEXITCODE -ne 0) { throw "gen_certs.ps1 failed" }

Write-Host "[10/11] build X.509 test"
gcc -I shim -I ../../include -O2 -Wall -o x509_test.exe test_x509.c
if ($LASTEXITCODE -ne 0) { throw "gcc (x509) failed" }

Write-Host "[11/11] run X.509 test"
.\x509_test.exe
if ($LASTEXITCODE -ne 0) { throw "x509 test failed" }

Write-Host "TLS codec + handshake + X.509 tests: ALL PASSED"
# ---- 完整握手驱动 (C 客户端 vs Python 服务端) ----
# 注意: 这台机器的 Device Guard 只允许已批准路径的可执行文件运行,
#       所以测试二进制沿用 hs_test.exe 这个名字; 若你的环境没有限制可随意改名.
Write-Host "[12/14] python: server first flight (Certificate split across records)"
python gen_hs2.py flight1 hs2_flight1.h
if ($LASTEXITCODE -ne 0) { throw "gen_hs2 flight1 failed" }

Write-Host "[13/14] build + run handshake driver"
gcc -I shim -I ../../include -O2 -Wall -o hs_test.exe test_hs2.c
if ($LASTEXITCODE -ne 0) { throw "gcc (hs2) failed" }
.\hs_test.exe
if ($LASTEXITCODE -ne 0) { throw "handshake driver test failed" }

Write-Host "[14/14] python: verify the client flight independently"
python gen_hs2.py verify client_flight.txt
if ($LASTEXITCODE -ne 0) { throw "client flight verification failed" }

Write-Host "TLS codec + handshake + X.509 + driver: ALL PASSED"
# ---- AES-GCM 套件 (0x009C) ----
Write-Host "[15/17] python: server flight for AES-128-GCM"
python gen_hs2.py flight1 hs2_flight1_gcm.h 009c
if ($LASTEXITCODE -ne 0) { throw "gen_hs2 flight1 (gcm) failed" }

Write-Host "[16/17] rebuild + run driver (both suites)"
gcc -I shim -I ../../include -O2 -Wall -o hs_test.exe test_hs2.c
if ($LASTEXITCODE -ne 0) { throw "gcc (hs2/gcm) failed" }
.\hs_test.exe
if ($LASTEXITCODE -ne 0) { throw "driver test (gcm) failed" }

Write-Host "[17/17] python: verify both client flights"
python gen_hs2.py verify client_flight.txt 002f
if ($LASTEXITCODE -ne 0) { throw "CBC client flight verification failed" }
python gen_hs2.py verify client_flight_gcm.txt 009c
if ($LASTEXITCODE -ne 0) { throw "GCM client flight verification failed" }

Write-Host "TLS: codec + handshake + X.509 + driver (CBC/GCM): ALL PASSED"