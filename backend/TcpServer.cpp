#include "TcpServer.h"
#include "CommandParser.h"
#include <iostream>
#include <cstring>
#include <sstream>

TcpServer::TcpServer(int p, StorageEngine& eng, AOFManager& aofMgr, ThreadPool& pool)
    : port(p), serverSocket(INVALID_SOCK), engine(eng), aof(aofMgr), threadPool(pool), isRunning(false) {}

TcpServer::~TcpServer() {
    stop();
}

bool TcpServer::start() {
    if (!initSocketSubsystem()) {
        return false;
    }

    serverSocket = socket(AF_INET, SOCK_STREAM, 0);
    if (serverSocket == INVALID_SOCK) {
        std::cerr << "Failed to create server socket. Error: " << getLastErrorSocket() << "\n";
        return false;
    }

    int opt = 1;
#ifdef _WIN32
    setsockopt(serverSocket, SOL_SOCKET, SO_REUSEADDR, (const char*)&opt, sizeof(opt));
#else
    setsockopt(serverSocket, SOL_SOCKET, SO_REUSEADDR, &opt, sizeof(opt));
#endif

    sockaddr_in serverAddr{};
    serverAddr.sin_family = AF_INET;
    serverAddr.sin_addr.s_addr = INADDR_ANY;
    serverAddr.sin_port = htons(static_cast<uint16_t>(port));

    if (bind(serverSocket, (struct sockaddr*)&serverAddr, sizeof(serverAddr)) == SOCK_ERR) {
        std::cerr << "Failed to bind server socket to port " << port << ". Error: " << getLastErrorSocket() << "\n";
        closeSocketHandle(serverSocket);
        serverSocket = INVALID_SOCK;
        return false;
    }

    if (listen(serverSocket, SOMAXCONN) == SOCK_ERR) {
        std::cerr << "Failed to listen on server socket. Error: " << getLastErrorSocket() << "\n";
        closeSocketHandle(serverSocket);
        serverSocket = INVALID_SOCK;
        return false;
    }

    isRunning.store(true);
    std::cout << "[FlashKV Server] Listening on port " << port << " with " 
              << threadPool.getThreadCount() << " worker threads.\n";
    return true;
}

void TcpServer::run() {
    while (isRunning.load()) {
        sockaddr_in clientAddr{};
#ifdef _WIN32
        int clientLen = sizeof(clientAddr);
#else
        socklen_t clientLen = sizeof(clientAddr);
#endif
        socket_t clientSocket = accept(serverSocket, (struct sockaddr*)&clientAddr, &clientLen);

        if (clientSocket == INVALID_SOCK) {
            if (!isRunning.load()) {
                break;
            }
            continue;
        }

        // Delegate client handling to thread pool
        threadPool.enqueue([this, clientSocket]() {
            this->handleClient(clientSocket);
        });
    }
}

void TcpServer::stop() {
    if (isRunning.load()) {
        isRunning.store(false);
        if (serverSocket != INVALID_SOCK) {
            closeSocketHandle(serverSocket);
            serverSocket = INVALID_SOCK;
        }
    }
}

void TcpServer::handleClient(socket_t clientSocket) {
    char buffer[4096];
    std::string accumulated;

    while (isRunning.load()) {
        int bytesRead = recv(clientSocket, buffer, sizeof(buffer) - 1, 0);
        if (bytesRead <= 0) {
            break; // Client disconnected or error
        }

        buffer[bytesRead] = '\0';
        accumulated.append(buffer, bytesRead);

        size_t newlinePos;
        while ((newlinePos = accumulated.find('\n')) != std::string::npos) {
            std::string line = accumulated.substr(0, newlinePos);
            accumulated.erase(0, newlinePos + 1);

            Command cmd = CommandParser::parse(line);
            if (cmd.type == CommandType::QUIT) {
                std::string ok = CommandParser::formatSimpleString("OK");
                send(clientSocket, ok.data(), static_cast<int>(ok.size()), 0);
                closeSocketHandle(clientSocket);
                return;
            }

            std::string response = processCommand(cmd, line);
            send(clientSocket, response.data(), static_cast<int>(response.size()), 0);
        }
    }

    closeSocketHandle(clientSocket);
}

std::string TcpServer::processCommand(const Command& cmd, const std::string& rawLine) {
    switch (cmd.type) {
        case CommandType::PING:
            return CommandParser::formatSimpleString("PONG");

        case CommandType::SET: {
            bool ok = engine.set(cmd.key, cmd.value, cmd.ttlSeconds);
            if (ok) {
                aof.append(rawLine);
                return CommandParser::formatSimpleString("OK");
            }
            return CommandParser::formatError("failed to set key");
        }

        case CommandType::GET: {
            std::string val;
            if (engine.get(cmd.key, val)) {
                return CommandParser::formatBulkString(val);
            }
            return CommandParser::formatNullBulkString();
        }

        case CommandType::DEL: {
            bool deleted = engine.del(cmd.key);
            if (deleted) {
                aof.append(rawLine);
                return CommandParser::formatInteger(1);
            }
            return CommandParser::formatInteger(0);
        }

        case CommandType::EXISTS:
            return CommandParser::formatInteger(engine.exists(cmd.key) ? 1 : 0);

        case CommandType::TTL:
            return CommandParser::formatInteger(engine.ttl(cmd.key));

        case CommandType::KEYS: {
            std::vector<std::string> keyList = engine.keys();
            return CommandParser::formatArray(keyList);
        }

        case CommandType::LRU: {
            std::vector<std::string> lruKeys = engine.lruOrder();
            return CommandParser::formatArray(lruKeys);
        }

        case CommandType::FLUSHDB:
            engine.flushDB();
            aof.append("FLUSHDB");
            return CommandParser::formatSimpleString("OK");

        case CommandType::STATS: {
            EngineStats st = engine.getStats();
            std::ostringstream oss;
            oss << "keys:" << st.keyCount << "\r\n"
                << "capacity:" << st.capacity << "\r\n"
                << "hits:" << st.totalHits << "\r\n"
                << "misses:" << st.totalMisses << "\r\n"
                << "commands_processed:" << st.totalCommands;
            return CommandParser::formatBulkString(oss.str());
        }

        default:
            return CommandParser::formatError("unknown or malformed command");
    }
}
