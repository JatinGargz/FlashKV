#pragma once

#include <string>
#include <cstdint>

struct Node {
    std::string key;
    std::string value;
    int64_t expireAtMs; // Epoch millisecond timestamp when key expires, or 0 if no TTL
    Node* prev;
    Node* next;

    Node(std::string k, std::string v, int64_t expireAt = 0)
        : key(std::move(k)), value(std::move(v)), expireAtMs(expireAt), prev(nullptr), next(nullptr) {}

    bool isExpired(int64_t currentEpochMs) const {
        return (expireAtMs > 0 && currentEpochMs >= expireAtMs);
    }
};
