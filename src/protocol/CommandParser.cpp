#include "CommandParser.h"
#include <algorithm>
#include <cctype>
#include <sstream>

static std::string toUpper(std::string str) {
    std::transform(str.begin(), str.end(), str.begin(), [](unsigned char c) {
        return std::toupper(c);
    });
    return str;
}

std::vector<std::string> CommandParser::tokenize(const std::string& rawLine) {
    std::vector<std::string> tokens;
    std::string current;
    bool inQuotes = false;

    for (size_t i = 0; i < rawLine.size(); ++i) {
        char c = rawLine[i];
        if (c == '\r' || c == '\n') {
            continue;
        }

        if (c == '"') {
            inQuotes = !inQuotes;
        } else if (std::isspace(static_cast<unsigned char>(c)) && !inQuotes) {
            if (!current.empty()) {
                tokens.push_back(current);
                current.clear();
            }
        } else {
            current.push_back(c);
        }
    }

    if (!current.empty()) {
        tokens.push_back(current);
    }
    return tokens;
}

Command CommandParser::parse(const std::string& rawLine) {
    Command cmd;
    cmd.rawLine = rawLine;

    std::vector<std::string> tokens = tokenize(rawLine);
    if (tokens.empty()) {
        cmd.type = CommandType::UNKNOWN;
        return cmd;
    }

    std::string verb = toUpper(tokens[0]);

    if (verb == "PING") {
        cmd.type = CommandType::PING;
    } else if (verb == "SET") {
        if (tokens.size() >= 3) {
            cmd.type = CommandType::SET;
            cmd.key = tokens[1];
            cmd.value = tokens[2];

            // Check for optional "EX <seconds>"
            for (size_t i = 3; i + 1 < tokens.size(); ++i) {
                if (toUpper(tokens[i]) == "EX") {
                    try {
                        cmd.ttlSeconds = std::stoll(tokens[i + 1]);
                    } catch (...) {
                        cmd.ttlSeconds = 0;
                    }
                    break;
                }
            }
        } else {
            cmd.type = CommandType::UNKNOWN;
        }
    } else if (verb == "GET") {
        if (tokens.size() >= 2) {
            cmd.type = CommandType::GET;
            cmd.key = tokens[1];
        } else {
            cmd.type = CommandType::UNKNOWN;
        }
    } else if (verb == "DEL") {
        if (tokens.size() >= 2) {
            cmd.type = CommandType::DEL;
            cmd.key = tokens[1];
        } else {
            cmd.type = CommandType::UNKNOWN;
        }
    } else if (verb == "EXISTS") {
        if (tokens.size() >= 2) {
            cmd.type = CommandType::EXISTS;
            cmd.key = tokens[1];
        } else {
            cmd.type = CommandType::UNKNOWN;
        }
    } else if (verb == "TTL") {
        if (tokens.size() >= 2) {
            cmd.type = CommandType::TTL;
            cmd.key = tokens[1];
        } else {
            cmd.type = CommandType::UNKNOWN;
        }
    } else if (verb == "KEYS") {
        cmd.type = CommandType::KEYS;
    } else if (verb == "LRU") {
        cmd.type = CommandType::LRU;
    } else if (verb == "FLUSHDB") {
        cmd.type = CommandType::FLUSHDB;
    } else if (verb == "STATS") {
        cmd.type = CommandType::STATS;
    } else if (verb == "QUIT" || verb == "EXIT") {
        cmd.type = CommandType::QUIT;
    } else {
        cmd.type = CommandType::UNKNOWN;
    }

    return cmd;
}

std::string CommandParser::formatSimpleString(const std::string& msg) {
    return "+" + msg + "\r\n";
}

std::string CommandParser::formatError(const std::string& err) {
    return "-ERR " + err + "\r\n";
}

std::string CommandParser::formatInteger(int64_t val) {
    return ":" + std::to_string(val) + "\r\n";
}

std::string CommandParser::formatBulkString(const std::string& val) {
    return "$" + std::to_string(val.size()) + "\r\n" + val + "\r\n";
}

std::string CommandParser::formatNullBulkString() {
    return "$-1\r\n";
}

std::string CommandParser::formatArray(const std::vector<std::string>& items) {
    std::string res = "*" + std::to_string(items.size()) + "\r\n";
    for (const auto& item : items) {
        res += formatBulkString(item);
    }
    return res;
}
