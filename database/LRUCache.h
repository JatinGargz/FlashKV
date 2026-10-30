#pragma once

#include "DoublyLinkedList.h"
#include <unordered_map>
#include <string>
#include <vector>
#include <utility>

class LRUCache {
private:
    size_t capacity;
    std::unordered_map<std::string, Node*> cache;
    DoublyLinkedList list;

public:
    explicit LRUCache(size_t maxCapacity = 10000);
    ~LRUCache();

    LRUCache(const LRUCache&) = delete;
    LRUCache& operator=(const LRUCache&) = delete;

    // Core cache operations
    bool get(const std::string& key, std::string& outValue, int64_t currentEpochMs);
    bool put(const std::string& key, const std::string& value, int64_t expireAtMs = 0);
    bool erase(const std::string& key);
    bool exists(const std::string& key, int64_t currentEpochMs);
    int64_t getTTLSeconds(const std::string& key, int64_t currentEpochMs);

    // Active expiration & eviction helpers
    std::vector<std::string> purgeExpiredKeys(int64_t currentEpochMs, size_t maxBatch = 100);

    // Snapshot & inspection
    std::vector<std::pair<std::string, std::string>> dumpAll(int64_t currentEpochMs);
    std::vector<std::string> getAllKeys(int64_t currentEpochMs);
    std::vector<std::string> getLRUOrder(int64_t currentEpochMs);

    size_t size() const { return cache.size(); }
    size_t getCapacity() const { return capacity; }
    void setCapacity(size_t newCap);
    void clear();
};
