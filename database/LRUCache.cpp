#include "LRUCache.h"

LRUCache::LRUCache(size_t maxCapacity) : capacity(maxCapacity > 0 ? maxCapacity : 10000) {}

LRUCache::~LRUCache() {
    clear();
}

bool LRUCache::get(const std::string& key, std::string& outValue, int64_t currentEpochMs) {
    auto it = cache.find(key);
    if (it == cache.end()) {
        return false;
    }

    Node* node = it->second;
    // Passive Expiration Check
    if (node->isExpired(currentEpochMs)) {
        erase(key);
        return false;
    }

    list.moveToHead(node);
    outValue = node->value;
    return true;
}

bool LRUCache::put(const std::string& key, const std::string& value, int64_t expireAtMs) {
    auto it = cache.find(key);
    if (it != cache.end()) {
        Node* node = it->second;
        node->value = value;
        node->expireAtMs = expireAtMs;
        list.moveToHead(node);
        return true;
    }

    // Check capacity for eviction
    if (cache.size() >= capacity) {
        Node* lruNode = list.removeTail();
        if (lruNode) {
            cache.erase(lruNode->key);
            delete lruNode;
        }
    }

    Node* newNode = new Node(key, value, expireAtMs);
    list.addToHead(newNode);
    cache[key] = newNode;
    return true;
}

bool LRUCache::erase(const std::string& key) {
    auto it = cache.find(key);
    if (it == cache.end()) {
        return false;
    }

    Node* node = it->second;
    list.removeNode(node);
    cache.erase(it);
    delete node;
    return true;
}

bool LRUCache::exists(const std::string& key, int64_t currentEpochMs) {
    auto it = cache.find(key);
    if (it == cache.end()) {
        return false;
    }

    if (it->second->isExpired(currentEpochMs)) {
        erase(key);
        return false;
    }
    return true;
}

int64_t LRUCache::getTTLSeconds(const std::string& key, int64_t currentEpochMs) {
    auto it = cache.find(key);
    if (it == cache.end()) {
        return -2; // Key does not exist
    }

    Node* node = it->second;
    if (node->isExpired(currentEpochMs)) {
        erase(key);
        return -2;
    }

    if (node->expireAtMs <= 0) {
        return -1; // Exists but has no TTL
    }

    int64_t remainingMs = node->expireAtMs - currentEpochMs;
    return (remainingMs > 0) ? (remainingMs / 1000) : 0;
}

std::vector<std::string> LRUCache::purgeExpiredKeys(int64_t currentEpochMs, size_t maxBatch) {
    std::vector<std::string> expiredKeys;
    for (auto it = cache.begin(); it != cache.end() && expiredKeys.size() < maxBatch; ) {
        if (it->second->isExpired(currentEpochMs)) {
            expiredKeys.push_back(it->first);
            Node* node = it->second;
            list.removeNode(node);
            delete node;
            it = cache.erase(it);
        } else {
            ++it;
        }
    }
    return expiredKeys;
}

std::vector<std::pair<std::string, std::string>> LRUCache::dumpAll(int64_t currentEpochMs) {
    std::vector<std::pair<std::string, std::string>> dump;
    for (auto it = cache.begin(); it != cache.end(); ) {
        if (it->second->isExpired(currentEpochMs)) {
            Node* node = it->second;
            list.removeNode(node);
            delete node;
            it = cache.erase(it);
        } else {
            dump.emplace_back(it->first, it->second->value);
            ++it;
        }
    }
    return dump;
}

std::vector<std::string> LRUCache::getAllKeys(int64_t currentEpochMs) {
    std::vector<std::string> keys;
    for (auto it = cache.begin(); it != cache.end(); ) {
        if (it->second->isExpired(currentEpochMs)) {
            Node* node = it->second;
            list.removeNode(node);
            delete node;
            it = cache.erase(it);
        } else {
            keys.push_back(it->first);
            ++it;
        }
    }
    return keys;
}

std::vector<std::string> LRUCache::getLRUOrder(int64_t currentEpochMs) {
    purgeExpiredKeys(currentEpochMs, 1000);
    return list.getKeysInOrder();
}

void LRUCache::setCapacity(size_t newCap) {
    capacity = (newCap > 0) ? newCap : 1;
    while (cache.size() > capacity) {
        Node* lruNode = list.removeTail();
        if (lruNode) {
            cache.erase(lruNode->key);
            delete lruNode;
        } else {
            break;
        }
    }
}

void LRUCache::clear() {
    list.clear();
    cache.clear();
}
