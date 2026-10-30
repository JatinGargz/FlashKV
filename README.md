# FlashKV — High-Performance In-Memory Key-Value Store

[![Deploy with Vercel](https://vercel.com/button)](https://vercel.com/new/clone?repository-url=https%3A%2F%2Fgithub.com%2FJatinGargz%2FFlashKV)

An industrial-grade, multi-threaded in-memory key-value database engine (Mini-Redis) written in **Modern C++ (C++17)**.

---

## Features
- **$O(1)$ LRU Cache:** Custom Doubly Linked List paired with `std::unordered_map` for constant-time lookups and capacity-constrained eviction.
- **TTL Expiration:** Hybrid active and passive key expiration mechanisms.
- **Concurrency:** Thread-safe state synchronization using Read-Write Locks (`std::shared_mutex`) for concurrent reading and serialized writing.
- **Worker Thread Pool:** Pre-allocated thread pool with task queues and condition variables preventing thread exhaustion.
- **TCP Socket Server:** Cross-platform network server handling Redis-like string/RESP protocol on port `6379`.
- **AOF Persistence:** Append-Only File logging for durability and automatic crash-recovery replay on server reboot.
- **Interactive CLI & Benchmark Suite:** Full terminal REPL and a load tester measuring throughput (QPS).

---

## Project Structure
```text
flashkv/
├── CMakeLists.txt              # CMake build configuration
├── src/
│   ├── engine/                 # Core DSA: Node, DoublyLinkedList, LRUCache, StorageEngine
│   ├── protocol/               # CommandParser, RESP serializer
│   ├── concurrency/            # ThreadPool, Task Queue
│   ├── persistence/            # AOFManager (Append-Only File)
│   ├── server/                 # Cross-platform TcpServer & SocketUtils
│   └── main.cpp                # Server entry point
├── client/
│   └── FlashKVClient.cpp       # Interactive CLI client
├── benchmark/
│   └── BenchmarkTool.cpp       # Multi-threaded load tester
└── tests/
    └── UnitTests.cpp           # Automated unit test suite
```

---

## Build Instructions

### Using CMake & Ninja / GCC:
```bash
mkdir build
cd build
cmake .. -G "Ninja"
ninja
```
Or directly with CMake:
```bash
cmake -B build
cmake --build build --config Release
```

---

## Running FlashKV

### 1. Run the Server
```bash
# Start server on default port 6379 with capacity 10000
./flashkv_server [port] [max_capacity]
```

### 2. Connect with CLI Client
```bash
./flashkv_client 127.0.0.1 6379
```
Example commands:
```text
flashkv> PING
PONG
flashkv> SET user:1 "Jatin" EX 60
OK
flashkv> GET user:1
"Jatin"
flashkv> TTL user:1
58
flashkv> DEL user:1
(integer) 1
flashkv> STATS
"keys:0\r\ncapacity:10000\r\nhits:1\r\nmisses:0\r\ncommands_processed:4"
flashkv> QUIT
```

### 3. Run Benchmark Load Tester
```bash
# Runs 10 concurrent threads, 500 requests per thread (10,000 total operations)
./flashkv_benchmark [threads] [ops_per_thread]
```

### 4. Run Unit Tests
```bash
./flashkv_tests
```

---

## FlashKV Auth Gateway — Ephemeral In-Memory 2FA System

An enterprise-grade, single-use email verification gateway built directly on top of the C++ FlashKV in-memory engine.

### Key Capabilities
- **Dual-Portal Web UI:**
  - **Sender Portal (`/` or `/sender`):** Dispatch security passcodes with custom scopes, adjustable TTL countdowns (30s, 60s, 120s, 300s), and a live C++ memory token registry.
  - **Receiver Portal (`/verify` or `/receiver`):** Recipient PIN verification screen with clipboard paste, sub-millisecond RAM validation, and a **Simulate Replay Attack** security test.
- **Single-Use Atomic Eviction:** Verified tokens are immediately purged via `DEL` in the same clock cycle, permanently preventing token replay attacks.
- **Dedicated Outbound SMTP:** Direct TLS dispatch via `flashkv.auth@gmail.com` with formatted security cards.
- **Real-Time Engine Telemetry:** Slide-out drawer displaying live active keys, cache hit rate, LRU DoublyLinkedList chain (`MRU → LRU`), AOF journal tail, and an interactive RESP CLI (`127.0.0.1:6379>`).

### Quick Start (Local)
Double-click or run:
```bat
launch_project.bat
```
This automatically boots `build/flashkv_server.exe` on port 6379 and launches the web console at `http://localhost:5000/`.

---

## Vercel Deployment

FlashKV includes native Vercel Serverless Function support:
```bash
npx vercel deploy --prod
```
- **Routing:** Configured via `vercel.json` to route web traffic to `api/index.py`.
- **Dual-Mode Engine:** Automatically connects to the native C++ engine via TCP socket when available, or seamlessly falls back to an embedded in-memory DoublyLinkedList LRU engine during serverless execution.

