#include "../01_core_cpp_engine/server/SocketUtils.h"
#include <iostream>
#include <string>
#include <vector>
#include <sstream>
#include <cstdint>

std::string formatServerResponse(const std::string& raw) {
    if (raw.empty()) return "(no response)";

    if (raw[0] == '+') {
        // Simple string: +OK\r\n
        return raw.substr(1, raw.find("\r\n") - 1);
    } else if (raw[0] == '-') {
        // Error: -ERR ...\r\n
        return "(error) " + raw.substr(5, raw.find("\r\n") - 5);
    } else if (raw[0] == ':') {
        // Integer: :123\r\n
        return "(integer) " + raw.substr(1, raw.find("\r\n") - 1);
    } else if (raw[0] == '$') {
        // Bulk string: $len\r\nval\r\n or $-1\r\n
        if (raw.rfind("$-1", 0) == 0) {
            return "(nil)";
        }
        size_t firstNewline = raw.find("\r\n");
        if (firstNewline != std::string::npos) {
            size_t secondNewline = raw.find("\r\n", firstNewline + 2);
            if (secondNewline != std::string::npos) {
                return "\"" + raw.substr(firstNewline + 2, secondNewline - (firstNewline + 2)) + "\"";
            }
        }
        return raw;
    } else if (raw[0] == '*') {
        // Array: *len\r\n...
        std::istringstream iss(raw);
        std::string line;
        std::getline(iss, line); // *len
        int count = 0;
        try {
            count = std::stoi(line.substr(1));
        } catch (...) {
            return raw;
        }

        if (count == 0) return "(empty list or set)";

        std::string result;
        for (int i = 1; i <= count; ++i) {
            std::string lenLine, valLine;
            if (std::getline(iss, lenLine) && std::getline(iss, valLine)) {
                // Remove trailing \r if present
                if (!valLine.empty() && valLine.back() == '\r') valLine.pop_back();
                result += std::to_string(i) + ") \"" + valLine + "\"\n";
            }
        }
        return result;
    }

    return raw;
}

int main(int argc, char* argv[]) {
    std::string host = "127.0.0.1";
    int port = 6379;

    if (argc >= 2) host = argv[1];
    if (argc >= 3) {
        try { port = std::stoi(argv[2]); } catch (...) {}
    }

    if (!initSocketSubsystem()) {
        std::cerr << "Failed to initialize network subsystem.\n";
        return 1;
    }

    socket_t clientSock = socket(AF_INET, SOCK_STREAM, 0);
    if (clientSock == INVALID_SOCK) {
        std::cerr << "Failed to create socket.\n";
        cleanupSocketSubsystem();
        return 1;
    }

    sockaddr_in serverAddr{};
    serverAddr.sin_family = AF_INET;
    serverAddr.sin_port = htons(static_cast<uint16_t>(port));
    inet_pton(AF_INET, host.c_str(), &serverAddr.sin_addr);

    std::cout << "Connecting to FlashKV server at " << host << ":" << port << "...\n";
    if (connect(clientSock, (struct sockaddr*)&serverAddr, sizeof(serverAddr)) == SOCK_ERR) {
        std::cerr << "Could not connect to FlashKV server on " << host << ":" << port << "\n";
        closeSocketHandle(clientSock);
        cleanupSocketSubsystem();
        return 1;
    }

    std::cout << "Connected! Type commands (e.g., SET k v, GET k, PING, STATS, QUIT).\n\n";

    std::string input;
    char buffer[8192];

    while (true) {
        std::cout << "flashkv " << host << ":" << port << "> ";
        if (!std::getline(std::cin, input)) {
            break;
        }

        if (input.empty()) continue;

        if (input == "exit" || input == "quit" || input == "QUIT") {
            std::string q = "QUIT\r\n";
            send(clientSock, q.data(), static_cast<int>(q.size()), 0);
            break;
        }

        std::string commandPayload = input + "\r\n";
        int sent = send(clientSock, commandPayload.data(), static_cast<int>(commandPayload.size()), 0);
        if (sent <= 0) {
            std::cerr << "Error: Connection lost.\n";
            break;
        }

        int bytesReceived = recv(clientSock, buffer, sizeof(buffer) - 1, 0);
        if (bytesReceived <= 0) {
            std::cerr << "Server closed the connection.\n";
            break;
        }

        buffer[bytesReceived] = '\0';
        std::string rawResponse(buffer, bytesReceived);
        std::cout << formatServerResponse(rawResponse) << "\n";
    }

    closeSocketHandle(clientSock);
    cleanupSocketSubsystem();
    return 0;
}
