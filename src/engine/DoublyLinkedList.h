#pragma once

#include "Node.h"
#include <cstddef>
#include <vector>

class DoublyLinkedList {
private:
    Node* head; // Dummy head sentinel
    Node* tail; // Dummy tail sentinel
    size_t nodeCount;

public:
    DoublyLinkedList();
    ~DoublyLinkedList();

    // Non-copyable
    DoublyLinkedList(const DoublyLinkedList&) = delete;
    DoublyLinkedList& operator=(const DoublyLinkedList&) = delete;

    // Core O(1) operations
    void addToHead(Node* node);
    void removeNode(Node* node);
    void moveToHead(Node* node);
    Node* removeTail();

    size_t size() const { return nodeCount; }
    bool empty() const { return nodeCount == 0; }
    void clear();
    std::vector<std::string> getKeysInOrder() const;
};
