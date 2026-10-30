#pragma once

#include "SocketUtils.h"
#include "StorageEngine.h"
#include "AOFManager.h"
#include "ThreadPool.h"
#include "Command.h"
#include <atomic>
#include <string>

class TcpServer {
private:
    int port;
    socket_t serverSocket;
    StorageEngine& engine;
    AOFManager& aof;
    ThreadPool& threadPool;
    std::atomic<bool> isRunning;

    void handleClient(socket_t clientSocket);
    std::string processCommand(const Command& cmd, const std::string& rawLine);

public:
    TcpServer(int port, StorageEngine& eng, AOFManager& aofMgr, ThreadPool& pool);
    ~TcpServer();

    TcpServer(const TcpServer&) = delete;
    TcpServer& operator=(const TcpServer&) = delete;

    bool start();
    void run();
    void stop();
};
