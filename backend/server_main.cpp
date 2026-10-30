#include "StorageEngine.h"
#include "AOFManager.h"
#include "ThreadPool.h"
#include "TcpServer.h"
#include <iostream>
#include <csignal>
#include <memory>

static TcpServer* g_server = nullptr;

void signalHandler(int signum) {
    std::cout << "\n[FlashKV Server] Caught signal " << signum << ". Shutting down cleanly...\n";
    if (g_server) {
        g_server->stop();
    }
}

int main(int argc, char* argv[]) {
    int port = 6379;
    size_t capacity = 10000;

    if (argc >= 2) {
        try {
            port = std::stoi(argv[1]);
        } catch (...) {
            port = 6379;
        }
    }

    if (argc >= 3) {
        try {
            capacity = std::stoull(argv[2]);
        } catch (...) {
            capacity = 10000;
        }
    }

    std::cout << "====================================================\n";
    std::cout << "   FlashKV — High-Performance In-Memory DB Engine   \n";
    std::cout << "====================================================\n";
    std::cout << "Configured Port:     " << port << "\n";
    std::cout << "Max Cache Capacity:  " << capacity << " keys\n";

    // 1. Initialize Storage Engine
    StorageEngine engine(capacity);

    // 2. Initialize and Replay Persistence (AOF)
    AOFManager aof("appendonly.aof");
    size_t replayed = aof.replay(engine);
    if (replayed > 0) {
        std::cout << "[Persistence] Replayed " << replayed << " commands from appendonly.aof\n";
    } else {
        std::cout << "[Persistence] Clean startup (no prior AOF data found).\n";
    }
    if (!aof.open()) {
        std::cerr << "[Warning] Failed to open appendonly.aof for appending writes.\n";
    }

    // 3. Initialize Thread Pool
    unsigned int hardwareThreads = std::thread::hardware_concurrency();
    size_t workerCount = (hardwareThreads > 0) ? hardwareThreads : 4;
    ThreadPool pool(workerCount);

    // 4. Start TCP Server
    TcpServer server(port, engine, aof, pool);
    g_server = &server;

    std::signal(SIGINT, signalHandler);
    std::signal(SIGTERM, signalHandler);

    if (!server.start()) {
        std::cerr << "[Fatal Error] Could not start TCP server.\n";
        cleanupSocketSubsystem();
        return 1;
    }

    server.run();

    cleanupSocketSubsystem();
    std::cout << "[FlashKV Server] Goodbye!\n";
    return 0;
}
