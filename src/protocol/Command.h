#pragma once

#include <string>
#include <cstdint>

enum class CommandType {
    PING,
    SET,
    GET,
    DEL,
    EXISTS,
    TTL,
    KEYS,
    LRU,
    FLUSHDB,
    STATS,
    QUIT,
    UNKNOWN
};

struct Command {
    CommandType type{CommandType::UNKNOWN};
    std::string key;
    std::string value;
    int64_t ttlSeconds{0};
    std::string rawLine;
};
