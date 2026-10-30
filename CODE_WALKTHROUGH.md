# FlashKV: Complete Code Walkthrough & Viva Guide

**Project:** FlashKV — High-Performance In-Memory Key-Value Store & Ephemeral 2FA Auth Gateway  
**Evaluator:** Dr. Gunjan Chugh  
**Course:** B.Tech Computer Science & Engineering (2nd Year)  
**Team:** RediSetGo  
**Live Production URL:** [https://flashkv-auth.vercel.app](https://flashkv-auth.vercel.app)  

---

## 1. System Architecture Overview

```
                                +-----------------------------+
                                |   Web Browser / End User    |
                                +--------------+--------------+
                                               |
                     +-------------------------+-------------------------+
                     | HTTP / REST (Port 5000)                           | HTTP / REST (Port 443)
                     v                                                   v
        +-----------------------------+                     +-----------------------------+
        |   02_web_2fa_gateway/       |                     |    api/ (Vercel Serverless) |
        |   auth_gateway.py           |                     |    index.py                 |
        |   (Dual-Portal Web Console) |                     |    (Edge Cloud Engine)      |
        +--------------+--------------+                     +--------------+--------------+
                       |                                                   |
                       | TCP Socket (RESP Protocol, Port 6379)             | TLS / SMTP
                       v                                                   v
        +-----------------------------+                     +-----------------------------+
        |   01_core_cpp_engine/       |                     |   Google SMTP (Gmail API)   |
        |   flashkv_server.exe        |                     |   flashkv.auth@gmail.com    |
        +--------------+--------------+                     +-----------------------------+
                       |
        +--------------+-------------------------------+
        |                                              |
        v                                              v
+-----------------------+                    +--------------------+
|  In-Memory Storage    |                    |  Disk Persistence  |
|  - LRU Eviction Cache |                    |  - appendonly.aof  |
|  - RW Spinlock / Lock |                    |  - Write-Ahead Log |
|  - Expire Millis TTL  |                    +--------------------+
+-----------------------+
```

---

## 2. Numbered Directory Structure & File Map

| Directory | Core Purpose | Evaluator Viva Topic |
|---|---|---|
| `01_core_cpp_engine/` | Native C++17 In-Memory Server & Data Structures | Custom LRU Cache, Concurrency, Socket I/O |
| `02_web_2fa_gateway/` | Python Dual-Portal 2FA Web Console | Full-Stack Integration, SMTP Automation |
| `03_cli_client/` | Interactive Terminal REPL Client | RESP Protocol, Direct Socket Comm |
| `04_benchmark_suite/` | Multi-Threaded Stress & Latency Benchmark | Concurrency, Throughput, Percentiles |
| `05_unit_tests/` | Automated Test Suite (Catch-style) | Unit Testing, Edge Cases, Durability |
| `06_academic_reports/`| 2-Page Academic Project Brief (PDF + HTML) | Academic Submission Documentation |

---

## 3. Deep-Dive: File-by-File Code Walkthrough

### 📁 `01_core_cpp_engine/` (Native In-Memory Database Server)

#### 1. `01_core_cpp_engine/engine/Node.h`
- **Data Structure:** Doubly Linked List Node.
- **Fields:**
  - `std::string key`: Key string.
  - `std::string val`: Stored value.
  - `int64_t expires_at`: Expiration timestamp in milliseconds since epoch (`-1` if persistent).
  - `Node* prev`, `Node* next`: Pointers for $O(1)$ bidirectional linking.
- **Viva Answer:** *"We store expiration metadata directly inside each node to allow single-pass TTL checks without auxiliary lookup tables."*

#### 2. `01_core_cpp_engine/engine/DoublyLinkedList.h` & `DoublyLinkedList.cpp`
- **Purpose:** Tracks access recency for cache replacement.
- **Key Methods:**
  - `addToHead(Node* node)`: Places newly inserted or updated items at the MRU (Most Recently Used) position in $O(1)$.
  - `moveToHead(Node* node)`: Promotes a accessed key to the head in $O(1)$.
  - `removeNode(Node* node)`: Unlinks any arbitrary node in $O(1)$.
  - `removeTail()`: Evicts the LRU (Least Recently Used) node from the tail in $O(1)$.
- **Viva Answer:** *"By maintaining dummy head and tail sentinel nodes, our list operations avoid edge-case null pointer checks, ensuring zero branch mispredictions."*

#### 3. `01_core_cpp_engine/engine/LRUCache.h` & `LRUCache.cpp`
- **Purpose:** Fixed-capacity cache eviction algorithm.
- **Data Structures Combined:**
  - `std::unordered_map<std::string, Node*> map_`: Provides $O(1)$ key lookup.
  - `DoublyLinkedList list_`: Maintains ordering in $O(1)$.
- **Viva Answer:** *"A hash table alone cannot maintain access order, and a linked list alone has $O(N)$ lookup. Combining both yields true $O(1)$ lookup and $O(1)$ eviction."*

#### 4. `01_core_cpp_engine/engine/StorageEngine.h` & `StorageEngine.cpp`
- **Purpose:** Master thread-safe database storage manager.
- **Key Features:**
  - **Thread-Safety:** Implemented via `mutable std::shared_mutex rw_mutex_`. Multiple readers execute concurrently (`std::shared_lock`), while mutations (`SET`, `DEL`, `EXPIRE`) acquire exclusive locks (`std::unique_lock`).
  - **TTL & Lazy Expiration:** When `GET` is invoked, `isExpired(node)` is evaluated. If expired, it triggers `evictExpired()` immediately.
  - **Active Expiration:** Periodic sweep scans a randomized sampling of keys to release memory proactively.
  - **Commands Supported:** `SET`, `GET`, `DEL`, `EXPIRE`, `TTL`, `PERSIST`, `EXISTS`, `KEYS`, `FLUSHALL`, `DBSIZE`.

#### 5. `01_core_cpp_engine/protocol/Command.h` & `CommandParser.h` / `CommandParser.cpp`
- **Purpose:** Implements the **RESP (Redis Serialization Protocol)**.
- **Serialization Format:**
  - Simple Strings: `+OK\r\n`
  - Error Strings: `-ERR unknown command\r\n`
  - Integers: `:1\r\n`
  - Bulk Strings: `$4\r\nECHO\r\n`
  - Arrays: `*2\r\n$3\r\nGET\r\n$4\r\nUSER\r\n`
- **Viva Answer:** *"Adhering strictly to RESP enables our engine to communicate seamlessly with existing standard Redis libraries and clients without proprietary drivers."*

#### 6. `01_core_cpp_engine/concurrency/ThreadPool.h` & `ThreadPool.cpp`
- **Purpose:** Worker thread pool for multi-client concurrency.
- **Design:**
  - Pre-allocates worker threads (`std::vector<std::thread>`).
  - Task queue guarded by `std::mutex` and signaled with `std::condition_variable`.
  - Distributes incoming TCP socket requests across available CPU cores to avoid thread creation overhead per request.

#### 7. `01_core_cpp_engine/persistence/AOFManager.h` & `AOFManager.cpp`
- **Purpose:** Append-Only File (AOF) durability engine (`appendonly.aof`).
- **Mechanism:**
  - **Write-Ahead Logging:** Every state-modifying command (`SET`, `DEL`, `EXPIRE`) is serialized to RESP and flushed to disk with `fsync`.
  - **Replay on Boot:** Upon server startup, `AOFManager::replay()` parses the AOF file and re-executes all recorded commands into memory, restoring state identically.

#### 8. `01_core_cpp_engine/server/SocketUtils.h` & `TcpServer.h` / `TcpServer.cpp`
- **Purpose:** High-performance TCP socket networking.
- **Features:** Cross-platform abstraction (Winsock2 on Windows, POSIX sockets on Linux), non-blocking socket handling, connection pooling, and request-response loop.

#### 9. `01_core_cpp_engine/main.cpp`
- **Purpose:** Server entry point.
- **Workflow:** Parses command-line port (default 6379) and cache capacity (default 10000), binds signal handlers (`SIGINT`, `SIGTERM`), initializes `StorageEngine`, boots `TcpServer`, and starts the event loop.

---

### 📁 `02_web_2fa_gateway/` (Dual-Portal 2FA Web Console)

#### `02_web_2fa_gateway/auth_gateway.py`
- **Architecture:** Dual-Portal Security System.
  - **Sender Portal (`/`):** Generates 6-digit cryptographic PINs, attaches metadata (Target Email, Action Scope e.g. Wire Transfer, Expiration TTL 10s–600s), writes the record to FlashKV via low-level TCP RESP client, and dispatches an HTML email via Google SMTP.
  - **Receiver Portal (`/verify`):** Dedicated recipient verification screen. Verifies PIN against FlashKV in RAM (sub-millisecond latency) and immediately executes an atomic single-use `DEL` purge to prevent replay attacks.
- **Styling:** Custom Industrial Carbon & High-Voltage Amber dark aesthetic, custom SVG logo, and zero external framework dependencies.

---

### 📁 `03_cli_client/` (Interactive Terminal REPL)

#### `03_cli_client/FlashKVClient.cpp`
- **Purpose:** Interactive terminal interface mimicking `redis-cli`.
- **Features:** Direct raw TCP socket connection, RESP message formatting, ANSI syntax highlighting, command history, and latency diagnostics.

---

### 📁 `04_benchmark_suite/` (Stress & Throughput Benchmarking)

#### `04_benchmark_suite/BenchmarkTool.cpp`
- **Purpose:** Concurrency stress testing tool.
- **Capabilities:**
  - Spawns $N$ concurrent worker threads.
  - Executes 100,000+ operations (`SET`, `GET`, `DEL`, `EXPIRE`).
  - Measures total runtime, Queries Per Second (QPS), and latency percentiles (p50, p95, p99).

---

### 📁 `05_unit_tests/` (Automated Verification Suite)

#### `05_unit_tests/UnitTests.cpp`
- **Tests Covered:**
  1. `testBasicSetGet`: Basic key insertion and retrieval.
  2. `testLRUEviction`: Verifies that exceeding maximum capacity evicts the oldest unaccessed item.
  3. `testTTLExpiration`: Verifies that keys with an expired TTL return nil.
  4. `testConcurrency`: Executes concurrent writes and reads across 8 threads to prove race-condition safety.
  5. `testAOFPersistence`: Writes keys, closes the engine, reloads from `appendonly.aof`, and verifies full recovery.

---

### 📁 `06_academic_reports/` (Evaluation Documentation)

- **`FlashKV_Brief_Project_Report.pdf`:** Formal 2-page project brief containing:
  - Project Title & Abstract.
  - Problem Statement & Objectives.
  - System Architecture & Core Innovations.
  - Comprehensive Benchmark & Empirical Results Table.
  - Evaluator & Candidate signature blocks.
- **`FlashKV_Brief_Project_Report.html`:** Pixel-perfect source document formatted for A4 printing.

---

## 4. Key Questions Dr. Gunjan Chugh Might Ask (Viva Cheat Sheet)

### Q1: "Why did you build your own Doubly Linked List instead of using `std::list`?"
> **Answer:** `std::list` does not expose direct node pointers without iterator overhead, making it difficult to maintain an iterator hash map safely during node splice operations. Our custom `Node` and `DoublyLinkedList` give us deterministic $O(1)$ unlinking and promotion with zero extraneous heap allocations.

### Q2: "How do you guarantee thread safety without slowing down reads?"
> **Answer:** We use `std::shared_mutex` (Reader-Writer lock). Read operations (`GET`, `EXISTS`, `TTL`) acquire `std::shared_lock`, allowing hundreds of concurrent clients to read simultaneously. Exclusive locks (`std::unique_lock`) are only acquired during mutations (`SET`, `DEL`, eviction), minimizing lock contention.

### Q3: "What prevents memory bloat if keys with TTL are never read again?"
> **Answer:** FlashKV implements a two-tier expiration policy:
> 1. **Lazy Eviction:** Checked during `GET`/`TTL` calls.
> 2. **Active Eviction:** An asynchronous background sweep periodically tests a random sample of keys with TTLs and purges expired entries, preventing passive memory leaks.

### Q4: "How does the Auth Gateway protect against replay attacks?"
> **Answer:** In `auth_gateway.py`, upon a successful passcode match, the server immediately triggers an atomic `DEL` command against the key in FlashKV. Even if the user clicks verify again or a malicious actor captures the PIN, subsequent checks return 404/expired within 0.14 milliseconds.
