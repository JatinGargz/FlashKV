#pragma once

#include <string>
#include <iostream>

#ifdef _WIN32
    #ifndef WIN32_LEAN_AND_MEAN
        #define WIN32_LEAN_AND_MEAN
    #endif
    #include <winsock2.h>
    #include <ws2tcpip.h>
    #pragma comment(lib, "ws2_32.lib")

    using socket_t = SOCKET;
    constexpr socket_t INVALID_SOCK = INVALID_SOCKET;
    constexpr int SOCK_ERR = SOCKET_ERROR;

    inline bool initSocketSubsystem() {
        WSADATA wsaData;
        int res = WSAStartup(MAKEWORD(2, 2), &wsaData);
        if (res != 0) {
            std::cerr << "WSAStartup failed with error: " << res << "\n";
            return false;
        }
        return true;
    }

    inline void cleanupSocketSubsystem() {
        WSACleanup();
    }

    inline void closeSocketHandle(socket_t sock) {
        if (sock != INVALID_SOCK) {
            closesocket(sock);
        }
    }

    inline int getLastErrorSocket() {
        return WSAGetLastError();
    }
#else
    #include <sys/types.h>
    #include <sys/socket.h>
    #include <netinet/in.h>
    #include <arpa/inet.h>
    #include <unistd.h>
    #include <errno.h>

    using socket_t = int;
    constexpr socket_t INVALID_SOCK = -1;
    constexpr int SOCK_ERR = -1;

    inline bool initSocketSubsystem() { return true; }
    inline void cleanupSocketSubsystem() {}
    inline void closeSocketHandle(socket_t sock) {
        if (sock >= 0) {
            close(sock);
        }
    }
    inline int getLastErrorSocket() {
        return errno;
    }
#endif
