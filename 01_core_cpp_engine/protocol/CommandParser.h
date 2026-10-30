#pragma once

#include "Command.h"
#include <vector>
#include <string>

class CommandParser {
public:
    static Command parse(const std::string& rawLine);
    static std::vector<std::string> tokenize(const std::string& rawLine);

    // Serialization responses (RESP-compatible)
    static std::string formatSimpleString(const std::string& msg);
    static std::string formatError(const std::string& err);
    static std::string formatInteger(int64_t val);
    static std::string formatBulkString(const std::string& val);
    static std::string formatNullBulkString();
    static std::string formatArray(const std::vector<std::string>& items);
};
