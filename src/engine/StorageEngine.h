#pragma once

#include "LRUCache.h"
#include <shared_mutex>
#include <thread>
#include <atomic>
#include <chrono>
#include <condition_variable>
#include <string>
#include <vector>
#include <utility>

struct EngineStats {
    size_t keyCount;
    size_t capacity;
    uint64_t totalHits;
    uint64_t totalMisses;
    uint64_t totalCommands;
};

class StorageEngine {
private:
    LRUCache cache;
    mutable std::shared_mutex rwMutex;

    // Background TTL cleaner
    std::atomic<bool> cleanerRunning;
    std::thread cleanerThread;
    std::condition_variable_any cleanerCv;

    // Metrics
    std::atomic<uint64_t> hits{0};
    std::atomic<uint64_t> misses{0};
    std::atomic<uint64_t> commandCount{0};

    void runActiveCleaner();

public:
    explicit StorageEngine(size_t capacity = 10000);
    ~StorageEngine();

    StorageEngine(const StorageEngine&) = delete;
    StorageEngine& operator=(const StorageEngine&) = delete;

    static int64_t getNowEpochMs();

    // Core operations
    bool set(const std::string& key, const std::string& value, int64_t ttlSeconds = 0);
    bool get(const std::string& key, std::string& outValue);
    bool del(const std::string& key);
    bool exists(const std::string& key);
    int64_t ttl(const std::string& key);

    void flushDB();
    EngineStats getStats() const;
    std::vector<std::string> keys();
    std::vector<std::string> lruOrder();
    std::vector<std::pair<std::string, std::string>> dump();
};
