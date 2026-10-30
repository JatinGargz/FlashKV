#include "DoublyLinkedList.h"

DoublyLinkedList::DoublyLinkedList() : nodeCount(0) {
    head = new Node("", "");
    tail = new Node("", "");
    head->next = tail;
    tail->prev = head;
}

DoublyLinkedList::~DoublyLinkedList() {
    clear();
    delete head;
    delete tail;
}

void DoublyLinkedList::addToHead(Node* node) {
    if (!node) return;
    node->next = head->next;
    node->prev = head;
    head->next->prev = node;
    head->next = node;
    nodeCount++;
}

void DoublyLinkedList::removeNode(Node* node) {
    if (!node || node == head || node == tail) return;
    node->prev->next = node->next;
    node->next->prev = node->prev;
    node->prev = nullptr;
    node->next = nullptr;
    if (nodeCount > 0) {
        nodeCount--;
    }
}

void DoublyLinkedList::moveToHead(Node* node) {
    if (!node || node == head || node == tail) return;
    removeNode(node);
    addToHead(node);
}

Node* DoublyLinkedList::removeTail() {
    if (empty()) return nullptr;
    Node* lruNode = tail->prev;
    if (lruNode == head) return nullptr;
    removeNode(lruNode);
    return lruNode;
}

void DoublyLinkedList::clear() {
    Node* curr = head->next;
    while (curr != tail && curr != nullptr) {
        Node* nextNode = curr->next;
        delete curr;
        curr = nextNode;
    }
    head->next = tail;
    tail->prev = head;
    nodeCount = 0;
}

std::vector<std::string> DoublyLinkedList::getKeysInOrder() const {
    std::vector<std::string> keys;
    Node* curr = head->next;
    while (curr != tail && curr != nullptr) {
        keys.push_back(curr->key);
        curr = curr->next;
    }
    return keys;
}
