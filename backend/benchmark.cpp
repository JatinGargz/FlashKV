#include "SocketUtils.h"
#include <iostream>
#include <vector>
#include <thread>
#include <atomic>
#include <chrono>
#include <string>
#include <cstdint>

void workerClient(const std::string& host, int port, int operationsPerThread, std::atomic<int>& successCount, std::atomic<int>& failCount) {
    socket_t sock = socket(AF_INET, SOCK_STREAM, 0);
    if (sock == INVALID_SOCK) {
        failCount += operationsPerThread;
        return;
    }

    sockaddr_in serverAddr{};
    serverAddr.sin_family = AF_INET;
    serverAddr.sin_port = htons(static_cast<uint16_t>(port));
    inet_pton(AF_INET, host.c_str(), &serverAddr.sin_addr);

    if (connect(sock, (struct sockaddr*)&serverAddr, sizeof(serverAddr)) == SOCK_ERR) {
        closeSocketHandle(sock);
        failCount += operationsPerThread;
        return;
    }

    char buffer[1024];
    for (int i = 0; i < operationsPerThread; ++i) {
        std::string key = "bench:key:" + std::to_string(i);
        std::string val = "bench_val_" + std::to_string(i);

        // Perform SET
        std::string cmd = "SET " + key + " " + val + "\r\n";
        if (send(sock, cmd.data(), static_cast<int>(cmd.size()), 0) <= 0) {
            failCount++;
            continue;
        }

        int n = recv(sock, buffer, sizeof(buffer) - 1, 0);
        if (n <= 0) {
            failCount++;
            continue;
        }

        // Perform GET
        cmd = "GET " + key + "\r\n";
        if (send(sock, cmd.data(), static_cast<int>(cmd.size()), 0) <= 0) {
            failCount++;
            continue;
        }

        n = recv(sock, buffer, sizeof(buffer) - 1, 0);
        if (n <= 0) {
            failCount++;
            continue;
        }

        successCount += 2; // 1 SET + 1 GET
    }

    closeSocketHandle(sock);
}

int main(int argc, char* argv[]) {
    std::string host = "127.0.0.1";
    int port = 6379;
    int totalThreads = 10;
    int opsPerThread = 500; // 500 sets + 500 gets = 1000 ops per thread -> 10,000 total

    if (argc >= 2) totalThreads = std::stoi(argv[1]);
    if (argc >= 3) opsPerThread = std::stoi(argv[2]);

    int totalExpectedOps = totalThreads * opsPerThread * 2;

    std::cout << "========================================================\n";
    std::cout << "   FlashKV Multi-Threaded Load Benchmark Tool           \n";
    std::cout << "========================================================\n";
    std::cout << "Target Server:        " << host << ":" << port << "\n";
    std::cout << "Concurrent Clients:   " << totalThreads << "\n";
    std::cout << "Operations / Client:  " << (opsPerThread * 2) << " (SET + GET)\n";
    std::cout << "Total Requests:       " << totalExpectedOps << "\n\n";

    if (!initSocketSubsystem()) {
        std::cerr << "Failed to initialize network subsystem.\n";
        return 1;
    }

    std::atomic<int> successCount{0};
    std::atomic<int> failCount{0};

    auto startTime = std::chrono::high_resolution_clock::now();

    std::vector<std::thread> threads;
    threads.reserve(totalThreads);
    for (int i = 0; i < totalThreads; ++i) {
        threads.emplace_back(workerClient, host, port, opsPerThread, std::ref(successCount), std::ref(failCount));
    }

    for (auto& t : threads) {
        if (t.joinable()) {
            t.join();
        }
    }

    auto endTime = std::chrono::high_resolution_clock::now();
    double elapsedSec = std::chrono::duration<double>(endTime - startTime).count();
    double qps = (elapsedSec > 0.0) ? (successCount.load() / elapsedSec) : 0.0;
    double avgLatencyMs = (successCount.load() > 0) ? (elapsedSec * 1000.0 / successCount.load()) : 0.0;

    std::cout << "----------------- Benchmark Results --------------------\n";
    std::cout << "Time Elapsed:         " << elapsedSec << " seconds\n";
    std::cout << "Successful Requests:  " << successCount.load() << "\n";
    std::cout << "Failed Requests:      " << failCount.load() << "\n";
    std::cout << "Throughput (QPS):     " << static_cast<uint64_t>(qps) << " queries/sec\n";
    std::cout << "Average Latency:      " << avgLatencyMs << " ms per request\n";
    std::cout << "========================================================\n";

    cleanupSocketSubsystem();
    return 0;
}
