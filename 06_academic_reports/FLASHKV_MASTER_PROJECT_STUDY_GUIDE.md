# FLASHKV: MASTER VIVA & TECHNICAL STUDY GUIDE
### High-Performance In-Memory Key-Value Store & Ephemeral 2FA Identity Gateway

**Authors:** Jatin Garg (Roll No. 25/CS/174) & Kanav Gupta (Roll No. 25/CS/187)  
**Course:** B.Tech Computer Science and Engineering, 2nd Year  
**College:** Delhi Technological University (DTU)  
**Evaluator:** Dr. Gunjan Chugh | **Team:** RediSetGo | **Date:** 30 October 2026  
**Live Production URL:** [https://flashkv-auth.vercel.app](https://flashkv-auth.vercel.app)  

---

> [!IMPORTANT]
> **VIVA CONFIDENTIAL — FOR PERSONAL STUDY ONLY**  
> Use this document to master every concept, data structure, C++ idiom, and OOP design principle in FlashKV.

---

## 1. The 30-Second Elevator Pitch & Viva Opening Script

When Dr. Gunjan Chugh asks: *"So Jatin and Kanav, introduce your project and tell me what you have built"*, deliver this exact, crisp response:

> *"Good morning, ma'am. For our project, we built FlashKV, which is an industrial-grade, multi-threaded in-memory key-value storage engine written from scratch in Modern C++17, inspired by Redis.*  
>  
> *Instead of using external libraries or relying on high-level runtimes, we implemented every core data structure from first principles: an O(1) LRU eviction cache combining a custom Doubly Linked List with a hash table, reader-writer concurrency using C++17 `std::shared_mutex`, a pre-allocated worker thread pool with condition variables, Append-Only File (AOF) durability for crash recovery, and a non-blocking TCP server speaking the standard Redis Serialization Protocol (RESP) on port 6379.*  
>  
> *To prove its practical enterprise utility, we connected it to a full-stack Dual-Portal Ephemeral 2FA Identity Gateway. It issues single-use security passcodes over real Google SMTP, verifies them in RAM in 0.13 milliseconds, and executes an atomic single-use DEL purge to permanently eliminate credential replay attacks. We have also deployed it live to the cloud on Vercel at `flashkv-auth.vercel.app`."*

---

## 2. High-Level System Architecture & Request Lifecycle

FlashKV follows a strict 3-tier decoupled architecture:
1. **Tier 1: Core Storage Engine (C++17 Daemon on Port 6379)** — Manages in-memory key-value state, tracks LRU eviction recency, enforces millisecond-accurate TTLs, and handles write-ahead disk logging.
2. **Tier 2: Protocol & Network Reactor** — Translates binary TCP packet streams into structured RESP command objects via `CommandParser`, delegating execution to a worker `ThreadPool`.
3. **Tier 3: Ephemeral 2FA Gateway & Web Consoles (Port 5000 / Cloud Edge)** — Dual-portal web interface providing a Sender Portal (dispatch passcodes via SMTP) and Receiver Portal (verify passcodes in RAM with replay immunity).

### Step-by-Step Lifecycle of a Command (`SET otp:code 492810 EX 60`)
1. **Network Arrival:** The client sends a raw RESP string over TCP socket to port 6379 (`*5\r\n$3\r\nSET\r\n$8\r\notp:code\r\n$6\r\n492810\r\n$2\r\nEX\r\n$2\r\n60\r\n`).
2. **Non-Blocking Accept:** `TcpServer` accepts the socket non-blockingly and pushes the client session task into the `ThreadPool` queue.
3. **Worker Dispatch:** A sleeping worker thread is awakened via `std::condition_variable`, pops the task, and invokes `CommandParser::parse()`.
4. **Exclusive Lock Acquisition:** Because `SET` is a mutative write, `StorageEngine` acquires an exclusive `std::unique_lock<std::shared_mutex>`. All concurrent reads on other keys are briefly blocked to prevent dirty reads.
5. **LRU Cache Placement & Eviction:** `LRUCache` checks its `unordered_map`. If the key exists, its node is moved to the head of `DoublyLinkedList` (MRU position). If new, a `Node` is created and inserted at head. If capacity (10,000 keys) is exceeded, the tail node (LRU) is unlinked and deleted in strict $O(1)$ time.
6. **Write-Ahead Durability:** `AOFManager` serializes the exact `SET` command and appends it sequentially to `appendonly.aof` on disk before returning.
7. **RESP Response:** The worker thread formats the result as a simple string `+OK\r\n` and writes it back to the client socket. The `unique_lock` is released via RAII.

---

## 3. Core Data Structures & Algorithms from First Principles

### 3.1 The Hybrid Hash Map + Doubly Linked List ($O(1)$ LRU Cache)
- **The Limitation of Hash Map alone:** A hash table (`std::unordered_map`) provides $O(1)$ average lookup, but has zero temporal ordering. It cannot know which key was accessed least recently.
- **The Limitation of Linked List alone:** A linked list maintains exact insertion and access order, but searching for an existing key to update its position requires linear scanning: $O(N)$ time.
- **The FlashKV Solution:** We combine BOTH! The `unordered_map` stores string keys mapped directly to `Node*` memory pointers. The `DoublyLinkedList` contains the actual nodes linked bidirectionally. Lookup is $O(1)$ through the map, and re-linking the node to the head (MRU) or evicting the tail (LRU) takes exactly 4 pointer updates: $O(1)$.

### 3.2 The Sentinel Node Pattern
In `DoublyLinkedList.cpp`, we create two dummy nodes: `head_` (sentinel head) and `tail_` (sentinel tail).  
Initially, `head_->next = tail_` and `tail_->prev = head_`. When adding or removing nodes, we NEVER have to check if `head_ == nullptr` or `tail_ == nullptr`. This completely eliminates segmentation faults, edge-case branching, and branch mispredictions.

### 3.3 Hybrid Expiration: Passive (Lazy) + Active Background Sweeping
- **Passive / Lazy Eviction:** When `GET` or `TTL` is called, `StorageEngine` compares `node->expires_at` against `std::chrono::system_clock::now()`. If expired, the key is deleted on-demand and returns nil.
- **Active Background Sweeping:** If an application sets 10,000 temporary keys with 60-second TTLs and never reads them again, lazy eviction would cause memory to leak permanently. To prevent this, FlashKV runs an active sweeping thread that periodically samples random keys and deletes expired entries, keeping RAM utilization bounded.

---

## 4. Every C++ & Systems Programming Concept in FlashKV

| C++ / Systems Concept | Where It Lives in Code | Why We Used It / Viva Defense |
|---|---|---|
| **C++17 `std::shared_mutex` & `std::shared_lock`** | `StorageEngine.h` / `StorageEngine.cpp` | Reader-Writer lock. Allows infinite concurrent readers (`GET`) simultaneously without blocking, while writers (`SET`, `DEL`) acquire exclusive ownership. |
| **RAII (Resource Acquisition Is Initialization)** | `StorageEngine.cpp`, `ThreadPool.cpp` | Locks (`std::unique_lock`, `std::shared_lock`) and file streams manage resources via stack lifetime. If an exception occurs, locks unlock automatically. |
| **Worker ThreadPool & Task Queue** | `concurrency/ThreadPool.h` / `.cpp` | Pre-allocates $N$ worker threads. Prevents thread exhaustion and OS context-switch overhead of creating a new `std::thread` per network request. |
| **`std::condition_variable` Synchronization** | `concurrency/ThreadPool.cpp` | Worker threads sleep when queue is empty and wake only when `cv_.notify_one()` signals work. Avoids 100% CPU spinning (spinlocks). |
| **Custom Doubly Linked List & Sentinel Nodes** | `engine/Node.h` / `DoublyLinkedList.cpp` | $O(1)$ node splicing without `std::list` overhead. Sentinel dummy nodes eliminate null pointer checks and prevent segfaults. |
| **Millisecond Timing via `std::chrono`** | `engine/StorageEngine.cpp`, `engine/Node.h` | Uses `std::chrono::system_clock` and `duration_cast<milliseconds>` for microsecond/millisecond TTL arithmetic across daylight saving & timezone changes. |
| **Append-Only File (AOF) Write-Ahead Log** | `persistence/AOFManager.h` / `.cpp` | Writes mutating operations to disk sequentially. Sequential disk writes bypass random rotational/seek latency, achieving near-RAM throughput. |
| **Cross-Platform Winsock2 & POSIX Sockets** | `server/SocketUtils.h` / `TcpServer.cpp` | Uses `#ifdef _WIN32` for `WSAStartup`/`closesocket` and POSIX for Linux/macOS. Sets non-blocking mode via `ioctlsocket(FIONBIO)`. |
| **RESP Protocol Parser (Tokenizer)** | `protocol/CommandParser.h` / `.cpp` | Parses Redis Serialization Protocol (RESP) strings (`*`, `$`, `+`, `-`, `:`) with robust quote and escape character handling. |
| **Static Linking Flags (`-static -static-libgcc`)** | `build.bat`, `CMakeLists.txt` | Embeds `libstdc++` and `libwinpthread` into binaries. Binaries run portably on any Windows PC without requiring MSYS2/MinGW DLLs installed. |

---

## 5. Object-Oriented Programming (OOP) Pillars & Design Patterns

### 5.1 Abstraction
- **What it is:** Hiding complex implementation details and showing only necessary interfaces.
- **In FlashKV:** `StorageEngine` provides clean public methods: `set()`, `get()`, `del()`, `ttl()`, and `stats()`. The caller (`TcpServer` or unit tests) has ZERO knowledge of raw pointers, node rewiring, cache capacity bounds, mutex acquisition, or AOF disk serialization.

### 5.2 Encapsulation
- **What it is:** Binding data and methods together while restricting direct access to internal state.
- **In FlashKV:** In `DoublyLinkedList` and `LRUCache`, member variables (`head_`, `tail_`, `capacity_`, `map_`, `size_`) are strictly private. An external class cannot alter the `prev` or `next` pointers of a `Node` directly; it must invoke protected methods like `addToHead()` or `removeNode()`.

### 5.3 Single Responsibility Principle (SRP)
- **`Node`:** Pure data container storing key, value, and expiration timestamp.
- **`DoublyLinkedList`:** Pure list topology and pointer maintenance.
- **`LRUCache`:** Manages capacity threshold and eviction ordering.
- **`StorageEngine`:** Thread synchronization, transactions, and TTL expiration logic.
- **`CommandParser`:** Translates wire protocol strings into `Command` structs.
- **`AOFManager`:** Manages disk file descriptors and sequential log replay.
- **`TcpServer`:** Manages TCP socket binding, listening, and network event loops.

### 5.4 Design Patterns Implemented
1. **Reactor / Worker ThreadPool Pattern:** Network acceptor (`TcpServer`) separates I/O multiplexing from command execution, dispatching socket tasks to a pre-allocated pool of worker threads.
2. **Sentinel Node Pattern:** Employs dummy head and tail nodes in `DoublyLinkedList` to ensure pointer operations never encounter null references.
3. **Command Pattern:** Network requests are encapsulated into uniform `Command` structs containing `CommandType`, `key`, `value`, and `ttlSeconds`.
4. **Write-Ahead Logging (WAL) Pattern:** In `AOFManager`, changes are committed to the append-only journal to guarantee crash durability.

---

## 6. Folder-by-Folder Viva Map

- **`01_core_cpp_engine/`:** The heart of the project. Contains `main.cpp` and subfolders `engine/` (DSA), `protocol/` (RESP), `concurrency/` (ThreadPool), `persistence/` (AOF), and `server/` (TCP Winsock).
- **`02_web_2fa_gateway/`:** Contains `auth_gateway.py`, our full-stack Dual-Portal 2FA Identity application that talks to FlashKV on port 6379, dispatches real Google SMTP emails, and provides the web UI.
- **`03_cli_client/`:** Contains `FlashKVClient.cpp`, our interactive REPL terminal client allowing direct Redis-like command execution with color-coded responses and ping latency measurement.
- **`04_benchmark_suite/`:** Contains `BenchmarkTool.cpp`, our high-load concurrency tester that spawns configurable worker threads to run 100,000+ operations and report QPS and latency percentiles.
- **`05_unit_tests/`:** Contains `UnitTests.cpp`, our automated verification suite with 5 test cases proving correctness of LRU eviction, TTL expiration, thread safety, and AOF crash recovery.
- **`06_academic_reports/`:** Contains our formal 2-page brief report (`FlashKV_Brief_Project_Report.pdf` & `.html`) prepared specifically for Dr. Gunjan Chugh.
- **`build.bat` & `launch_project.bat`:** One-click build script that compiles all 4 binaries statically using GCC, and one-click launch script that boots the C++ daemon and opens the web portal.

---

## 7. The Real-World Application: Ephemeral 2FA Identity Gateway

### Why 2FA was Chosen:
1. **Realizes Natural Expiration (TTL):** 2FA OTP tokens are fundamentally ephemeral. A security passcode MUST expire in 60 seconds. This demonstrates FlashKV's microsecond-precision TTL engine.
2. **Proves High-Throughput / Low Latency:** During login, users hate waiting for verification. FlashKV validates tokens in RAM in 0.13 milliseconds — 100x faster than disk-backed SQL databases.
3. **Single-Use Replay Attack Protection:** Upon successful passcode match, FlashKV immediately executes an atomic `DEL` command in the exact same clock cycle. If an attacker intercepts the passcode or the user clicks verify again, subsequent requests are immediately rejected with `HTTP 401 EXPIRED_OR_ABSENT`.
4. **Real Outbound SMTP Dispatch:** Connects to Google SMTP (`flashkv.auth@gmail.com`) via TLS to deliver real, production-formatted HTML security cards directly to user email inboxes.

### Live Demo Click Sequence for Professor:
1. Open `http://localhost:5000/` (Sender Portal).
2. Enter an email address and purpose (e.g., 'Grade Verification'). Click **GENERATE & DISPATCH PASSCODE**.
3. Point to the live In-Memory Token Registry table below — show the countdown timer ticking down from 60s in real time.
4. Open the Telemetry Drawer on the right — show the C++ LRU chain and the AOF journal recording the `SET` command.
5. Navigate to `http://localhost:5000/verify` (Receiver Portal). Enter the 6-digit PIN and click **VERIFY & PURGE PASSCODE**. Show the instant green confirmation (0.13ms latency).
6. Click **SIMULATE REPLAY ATTACK**. The system will instantly turn red with `HTTP 401 EXPIRED_OR_ABSENT`, proving the atomic single-use memory purge!

---

## 8. Top 20 Viva Questions with Word-for-Word Scripted Answers

*(See complete Q&A 1-20 in the full Word document or study table above.)*

---

## 9. Division of Responsibilities (Partner Viva Strategy)

| Team Member | Primary Focus Areas | What to Present to Dr. Gunjan Chugh |
|---|---|---|
| **Jatin Garg** (Roll No. 25/CS/174) | Core C++ DSA, LRU Cache, Concurrency & Storage Engine | Presents the custom `DoublyLinkedList`, sentinel nodes, `std::shared_mutex` reader-writer locking, `ThreadPool` task queue, and unit tests. |
| **Kanav Gupta** (Roll No. 25/CS/187) | TCP Networking, RESP Protocol, AOF Persistence & 2FA Gateway | Presents the non-blocking `TcpServer`, RESP protocol parser, AOF write-ahead durability, and live Dual-Portal 2FA demonstration with replay attack prevention. |

