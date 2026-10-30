@echo off
setlocal
echo ===============================================================
echo   Building FlashKV C++ Binaries with GCC / G++ (Static Link)
echo   Team RediSetGo: Jatin Garg (25/CS/174) & Kanav Gupta (25/CS/187)
echo   Evaluator: Dr. Gunjan Chugh ^| DTU CSE 2nd Year
echo ===============================================================
echo.

if not exist "build" mkdir "build"

set GXX=g++
where g++ >nul 2>nul
if %ERRORLEVEL% neq 0 (
    if exist "C:\msys64\ucrt64\bin\g++.exe" (
        set GXX=C:\msys64\ucrt64\bin\g++.exe
    ) else if exist "C:\msys64\mingw64\bin\g++.exe" (
        set GXX=C:\msys64\mingw64\bin\g++.exe
    ) else (
        echo [ERROR] g++ compiler not found in PATH or standard MSYS2 locations.
        pause
        exit /b 1
    )
)

set CXXFLAGS=-std=c++17 -O3 -static -static-libgcc -static-libstdc++ -Idatabase -Ibackend

echo Using compiler: %GXX%
echo Flags: %CXXFLAGS%
echo.

echo [1/4] Compiling flashkv_server.exe...
%GXX% %CXXFLAGS% ^
  backend/server_main.cpp ^
  database/DoublyLinkedList.cpp ^
  database/LRUCache.cpp ^
  database/StorageEngine.cpp ^
  backend/CommandParser.cpp ^
  backend/ThreadPool.cpp ^
  database/AOFManager.cpp ^
  backend/TcpServer.cpp ^
  -o build/flashkv_server.exe -lws2_32
if %ERRORLEVEL% neq 0 ( echo [FAILED] flashkv_server compilation failed! & exit /b 1 )
echo [OK] build/flashkv_server.exe generated.

echo [2/4] Compiling flashkv_client.exe...
%GXX% %CXXFLAGS% backend/cli_client.cpp -o build/flashkv_client.exe -lws2_32
if %ERRORLEVEL% neq 0 ( echo [FAILED] flashkv_client compilation failed! & exit /b 1 )
echo [OK] build/flashkv_client.exe generated.

echo [3/4] Compiling flashkv_benchmark.exe...
%GXX% %CXXFLAGS% backend/benchmark.cpp -o build/flashkv_benchmark.exe -lws2_32
if %ERRORLEVEL% neq 0 ( echo [FAILED] flashkv_benchmark compilation failed! & exit /b 1 )
echo [OK] build/flashkv_benchmark.exe generated.

echo [4/4] Compiling flashkv_tests.exe...
%GXX% %CXXFLAGS% ^
  backend/unit_tests.cpp ^
  database/DoublyLinkedList.cpp ^
  database/LRUCache.cpp ^
  database/StorageEngine.cpp ^
  backend/CommandParser.cpp ^
  backend/ThreadPool.cpp ^
  database/AOFManager.cpp ^
  backend/TcpServer.cpp ^
  -o build/flashkv_tests.exe -lws2_32
if %ERRORLEVEL% neq 0 ( echo [FAILED] flashkv_tests compilation failed! & exit /b 1 )
echo [OK] build/flashkv_tests.exe generated.

echo.
echo ===============================================================
echo   All 4 FlashKV binaries successfully compiled in build\
echo ===============================================================
