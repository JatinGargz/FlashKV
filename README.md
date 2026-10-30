# FlashKV — High-Performance In-Memory Key-Value Store & 2FA Auth Gateway

[![Live Demo on Vercel](https://img.shields.io/badge/Vercel-Live%20Production-black?style=for-the-badge&logo=vercel)](https://flashkv-auth.vercel.app/)
[![C++17](https://img.shields.io/badge/C%2B%2B-17-blue.svg?style=for-the-badge&logo=c%2B%2B)](https://en.cppreference.com/w/cpp/17)
[![Platform](https://img.shields.io/badge/Platform-Windows%20%7C%20Linux%20%7C%20Cloud-orange.svg?style=for-the-badge)]()
[![Evaluator](https://img.shields.io/badge/Evaluator-Dr.%20Gunjan%20Chugh-red.svg?style=for-the-badge)]()

An industrial-grade, multi-threaded in-memory key-value database engine (Mini-Redis) written in **Modern C++ (C++17)** with an integrated **Dual-Portal Ephemeral 2FA Web Console**.

- **Production Cloud Deployment:** [https://flashkv-auth.vercel.app/](https://flashkv-auth.vercel.app/)
- **Receiver Verification Screen:** [https://flashkv-auth.vercel.app/verify](https://flashkv-auth.vercel.app/verify)
- **Academic Project Brief (2-Page PDF):** [`06_academic_reports/FlashKV_Brief_Project_Report.pdf`](file:///C:/Users/Jatin/.gemini/antigravity/scratch/flashkv/06_academic_reports/FlashKV_Brief_Project_Report.pdf)
- **Viva & Code Defense Guide:** [`CODE_WALKTHROUGH.md`](file:///C:/Users/Jatin/.gemini/antigravity/scratch/flashkv/CODE_WALKTHROUGH.md)

---

## 📂 Project Organization & Code Map

The project repository is structured with descriptive, numbered directories to make code inspection and academic evaluation effortless:

```text
flashkv/
├── 01_core_cpp_engine/            # Native C++ In-Memory Storage Engine
│   ├── engine/                    # Core DSA: Node, DoublyLinkedList, LRUCache, StorageEngine
│   ├── protocol/                  # Command, CommandParser (RESP Serialization Protocol)
│   ├── concurrency/               # ThreadPool, Task Queue with Condition Variables
│   ├── persistence/               # AOFManager (Append-Only File Write-Ahead Logging)
│   ├── server/                    # Cross-platform TcpServer & SocketUtils (Winsock2 / POSIX)
│   └── main.cpp                   # Server entry point & signal handling
├── 02_web_2fa_gateway/            # Dual-Portal Ephemeral 2FA Security Console
│   └── auth_gateway.py            # HTTP Server, Gmail SMTP dispatcher, low-level RESP client
├── 03_cli_client/                 # Interactive Terminal REPL Client
│   └── FlashKVClient.cpp          # redis-cli clone with direct TCP socket communication
├── 04_benchmark_suite/            # Stress & Performance Load Tester
│   └── BenchmarkTool.cpp          # Multi-threaded throughput (QPS) & latency percentiles (p50/p95/p99)
├── 05_unit_tests/                 # Automated Verification Suite
│   └── UnitTests.cpp              # Catch-style tests: LRU eviction, TTL, persistence, concurrency
├── 06_academic_reports/           # Evaluation Documentation
│   ├── FlashKV_Brief_Project_Report.pdf  # Exact 2-page project brief for Dr. Gunjan Chugh
│   └── FlashKV_Brief_Project_Report.html # A4 printable HTML report source
├── api/                           # Vercel Serverless Edge API
│   └── index.py                   # Serverless gateway functions for production deployment
├── public/                        # Static edge web portal assets
│   └── index.html                 # Sender & Receiver Web Portals with Industrial Carbon theme
├── build/                         # Compiled static binaries (flashkv_server, flashkv_client, etc.)
├── build.bat                      # One-click standalone GCC static build script
├── launch_project.bat             # One-click startup script (Boots C++ server + Web console)
├── CMakeLists.txt                 # Modern CMake build configuration
├── vercel.json                    # Vercel Edge routing and rewrite definitions
└── CODE_WALKTHROUGH.md            # Comprehensive viva code explanation & question-defense guide
```

---

## ⚡ Core Technical Innovations

1. **$O(1)$ LRU Cache:** Custom Doubly Linked List paired with `std::unordered_map` for constant-time lookups and capacity-constrained eviction without runtime heap reallocations.
2. **Hybrid TTL Expiration:** Millisecond-accurate timestamp checking upon read (`lazy`) paired with periodic sampling sweep (`active`) to eliminate passive memory bloat.
3. **Reader-Writer Concurrency:** `std::shared_mutex` allows hundreds of parallel read requests (`std::shared_lock`) while serializing state mutations (`std::unique_lock`).
4. **Pre-Allocated Worker Thread Pool:** Fixed worker pool prevents thread thrashing and OS exhaustion under extreme load.
5. **Durability via AOF:** Append-Only File (`appendonly.aof`) write-ahead logging with deterministic startup replay.
6. **Dual-Portal Single-Use 2FA:** Microsecond-latency in-memory passcode validation with single-use atomic `DEL` purge to permanently eliminate replay vulnerabilities.

---

## 🚀 Quick Start Instructions

### Option 1: Direct One-Click Launch (Windows)
Double-click `launch_project.bat` or run:
```bat
launch_project.bat
```
*Automatically starts the C++ storage daemon on port `6379` and opens the Dual-Portal Web Console at `http://localhost:5000/`.*

### Option 2: Recompile with `build.bat`
```bat
build.bat
```
*Compiles all 4 binaries with `-O3 -static` using GCC/G++ directly into `build\`.*

### Option 3: Build with CMake
```bash
cmake -B build
cmake --build build --config Release
```

---

## 💻 Interactive Terminal CLI Usage

Connect directly to the C++ server via the terminal client:
```bash
./build/flashkv_client.exe 127.0.0.1 6379
```

Supported Commands:
```text
flashkv> PING
PONG
flashkv> SET user:101 "Alice" EX 60
OK
flashkv> GET user:101
"Alice"
flashkv> TTL user:101
58
flashkv> DEL user:101
(integer) 1
flashkv> STATS
"keys:0\r\ncapacity:10000\r\nhits:1\r\nmisses:0\r\ncommands_processed:4"
flashkv> QUIT
```

---

## 🧪 Automated Unit Tests & Benchmarking

### Run the Automated Unit Tests:
```bash
./build/flashkv_tests.exe
```
Output:
```text
========================================================
           FlashKV Core Engine Unit Tests               
========================================================
[RUNNING] test_DoublyLinkedList... [PASS]
[RUNNING] test_LRUCacheEviction... [PASS]
[RUNNING] test_StorageEngineTTL... [PASS]
[RUNNING] test_CommandParser...   [PASS]
[RUNNING] test_AOFRecovery...      [PASS]
========================================================
Tests Summary: 5 Passed, 0 Failed.
========================================================
```

### Run the Benchmark Suite:
```bash
./build/flashkv_benchmark.exe 8 12500
```
*Runs 8 concurrent worker threads executing 100,000 requests, reporting total throughput (QPS) and latency distributions.*

---

## 🌐 Live Cloud Deployment

- **Production URL:** [https://flashkv-auth.vercel.app/](https://flashkv-auth.vercel.app/)
- **Receiver Screen:** [https://flashkv-auth.vercel.app/verify](https://flashkv-auth.vercel.app/verify)
- Continuous deployment is enabled via the GitHub repository [`JatinGargz/flashkv-auth`](https://github.com/JatinGargz/flashkv-auth).
