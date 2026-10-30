#pragma once

#include "StorageEngine.h"
#include <string>
#include <fstream>
#include <mutex>

class AOFManager {
private:
    std::string filePath;
    std::ofstream fileStream;
    std::mutex fileMutex;
    bool enabled;

public:
    explicit AOFManager(std::string path = "appendonly.aof");
    ~AOFManager();

    AOFManager(const AOFManager&) = delete;
    AOFManager& operator=(const AOFManager&) = delete;

    bool open();
    void close();

    void append(const std::string& rawCommandLine);
    size_t replay(StorageEngine& engine);
    bool rewrite(StorageEngine& engine);

    const std::string& getFilePath() const { return filePath; }
};
