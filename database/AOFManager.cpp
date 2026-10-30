#include "AOFManager.h"
#include "CommandParser.h"
#include <iostream>
#include <algorithm>
#include <cstdio>

AOFManager::AOFManager(std::string path)
    : filePath(std::move(path)), enabled(true) {}

AOFManager::~AOFManager() {
    close();
}

bool AOFManager::open() {
    std::lock_guard<std::mutex> lock(fileMutex);
    fileStream.open(filePath, std::ios::out | std::ios::app);
    return fileStream.is_open();
}

void AOFManager::close() {
    std::lock_guard<std::mutex> lock(fileMutex);
    if (fileStream.is_open()) {
        fileStream.flush();
        fileStream.close();
    }
}

void AOFManager::append(const std::string& rawCommandLine) {
    if (!enabled) return;

    std::string clean = rawCommandLine;
    clean.erase(std::remove(clean.begin(), clean.end(), '\r'), clean.end());
    clean.erase(std::remove(clean.begin(), clean.end(), '\n'), clean.end());

    if (clean.empty()) return;

    std::lock_guard<std::mutex> lock(fileMutex);
    if (fileStream.is_open()) {
        fileStream << clean << "\n";
        fileStream.flush();
    }
}

size_t AOFManager::replay(StorageEngine& engine) {
    std::ifstream in(filePath);
    if (!in.is_open()) {
        return 0; // No prior AOF file exists, clean start
    }

    size_t count = 0;
    std::string line;
    while (std::getline(in, line)) {
        if (line.empty() || line[0] == '#') {
            continue;
        }

        Command cmd = CommandParser::parse(line);
        if (cmd.type == CommandType::SET) {
            engine.set(cmd.key, cmd.value, cmd.ttlSeconds);
            count++;
        } else if (cmd.type == CommandType::DEL) {
            engine.del(cmd.key);
            count++;
        } else if (cmd.type == CommandType::FLUSHDB) {
            engine.flushDB();
            count++;
        }
    }

    return count;
}

bool AOFManager::rewrite(StorageEngine& engine) {
    std::lock_guard<std::mutex> lock(fileMutex);
    if (fileStream.is_open()) {
        fileStream.flush();
        fileStream.close();
    }

    std::string tempPath = filePath + ".tmp";
    std::ofstream out(tempPath, std::ios::out | std::ios::trunc);
    if (!out.is_open()) {
        fileStream.open(filePath, std::ios::out | std::ios::app);
        return false;
    }

    auto data = engine.dump();
    for (const auto& kv : data) {
        out << "SET " << kv.first << " \"" << kv.second << "\"\n";
    }
    out.flush();
    out.close();

    ::remove(filePath.c_str());
    ::rename(tempPath.c_str(), filePath.c_str());

    fileStream.open(filePath, std::ios::out | std::ios::app);
    return fileStream.is_open();
}
