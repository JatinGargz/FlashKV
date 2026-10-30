#include "engine/DoublyLinkedList.h"
#include "engine/LRUCache.h"
#include "engine/StorageEngine.h"
#include "protocol/CommandParser.h"
#include "persistence/AOFManager.h"
#include <iostream>
#include <cassert>
#include <chrono>
#include <thread>
#include <cstdio>

static int g_testsPassed = 0;
static int g_testsFailed = 0;

#define TEST_ASSERT(cond, msg) \
    do { \
        if (!(cond)) { \
            std::cerr << "  [FAIL] " << msg << " (line " << __LINE__ << ")\n"; \
            g_testsFailed++; \
            return; \
        } \
    } while(0)

#define RUN_TEST(fn) \
    do { \
        std::cout << "[RUNNING] " << #fn << "...\n"; \
        int before = g_testsFailed; \
        fn(); \
        if (g_testsFailed == before) { \
            std::cout << "  [PASS] " << #fn << "\n"; \
            g_testsPassed++; \
        } \
    } while(0)

void test_DoublyLinkedList() {
    DoublyLinkedList list;
    TEST_ASSERT(list.empty(), "List should initially be empty");
    TEST_ASSERT(list.size() == 0, "List size should be 0");

    Node* n1 = new Node("k1", "v1");
    Node* n2 = new Node("k2", "v2");
    list.addToHead(n1);
    list.addToHead(n2);
    TEST_ASSERT(list.size() == 2, "List size should be 2");

    Node* tail = list.removeTail();
    TEST_ASSERT(tail != nullptr, "Tail node should not be null");
    TEST_ASSERT(tail->key == "k1", "Tail should be the first inserted node k1");
    delete tail;

    TEST_ASSERT(list.size() == 1, "List size should be 1 after removal");
}

void test_LRUCacheEviction() {
    LRUCache cache(2); // Capacity of 2
    int64_t now = 1000;

    cache.put("a", "1", 0);
    cache.put("b", "2", 0);
    TEST_ASSERT(cache.size() == 2, "Cache size should be 2");

    std::string val;
    TEST_ASSERT(cache.get("a", val, now) && val == "1", "Key 'a' should be retrieved and moved to head");

    // Insert 'c', capacity 2 -> 'b' is LRU and should be evicted!
    cache.put("c", "3", 0);
    TEST_ASSERT(cache.size() == 2, "Cache size should stay at 2");

    TEST_ASSERT(!cache.get("b", val, now), "Key 'b' must have been evicted");
    TEST_ASSERT(cache.get("a", val, now) && val == "1", "Key 'a' should still exist");
    TEST_ASSERT(cache.get("c", val, now) && val == "3", "Key 'c' should exist");
}

void test_StorageEngineTTL() {
    StorageEngine engine(100);

    engine.set("tempKey", "tempValue", 1); // 1 second TTL
    std::string val;
    TEST_ASSERT(engine.get("tempKey", val) && val == "tempValue", "tempKey should exist immediately");

    // Sleep 1.2 seconds to allow passive/active expiration
    std::this_thread::sleep_for(std::chrono::milliseconds(1200));

    TEST_ASSERT(!engine.get("tempKey", val), "tempKey should have expired and returned false");
    TEST_ASSERT(engine.ttl("tempKey") == -2, "TTL for expired key should be -2");
}

void test_CommandParser() {
    Command c1 = CommandParser::parse("SET mykey \"hello world\" EX 60");
    TEST_ASSERT(c1.type == CommandType::SET, "Command should be SET");
    TEST_ASSERT(c1.key == "mykey", "Key should be 'mykey'");
    TEST_ASSERT(c1.value == "hello world", "Value should be 'hello world'");
    TEST_ASSERT(c1.ttlSeconds == 60, "TTL should be 60");

    Command c2 = CommandParser::parse("get mykey");
    TEST_ASSERT(c2.type == CommandType::GET, "Command should be case-insensitive GET");
    TEST_ASSERT(c2.key == "mykey", "Key should be 'mykey'");

    Command c3 = CommandParser::parse("ping");
    TEST_ASSERT(c3.type == CommandType::PING, "Command should be PING");

    std::string resp = CommandParser::formatBulkString("data");
    TEST_ASSERT(resp == "$4\r\ndata\r\n", "Bulk string formatting matches RESP");
}

void test_AOFRecovery() {
    const std::string testAofFile = "test_appendonly.aof";
    std::remove(testAofFile.c_str());

    {
        AOFManager aof(testAofFile);
        TEST_ASSERT(aof.open(), "AOF file should open for writing");
        aof.append("SET user:1 Alice");
        aof.append("SET user:2 Bob");
        aof.append("DEL user:1");
    }

    // Replay onto a fresh engine
    StorageEngine freshEngine(100);
    AOFManager aofRecovery(testAofFile);
    size_t count = aofRecovery.replay(freshEngine);
    TEST_ASSERT(count == 3, "Should have replayed 3 commands");

    std::string val;
    TEST_ASSERT(!freshEngine.get("user:1", val), "user:1 should be deleted");
    TEST_ASSERT(freshEngine.get("user:2", val) && val == "Bob", "user:2 should be Bob");

    std::remove(testAofFile.c_str());
}

int main() {
    std::cout << "========================================================\n";
    std::cout << "           FlashKV Core Engine Unit Tests               \n";
    std::cout << "========================================================\n";

    RUN_TEST(test_DoublyLinkedList);
    RUN_TEST(test_LRUCacheEviction);
    RUN_TEST(test_StorageEngineTTL);
    RUN_TEST(test_CommandParser);
    RUN_TEST(test_AOFRecovery);

    std::cout << "========================================================\n";
    std::cout << "Tests Summary: " << g_testsPassed << " Passed, " 
              << g_testsFailed << " Failed.\n";
    std::cout << "========================================================\n";

    return (g_testsFailed == 0) ? 0 : 1;
}
