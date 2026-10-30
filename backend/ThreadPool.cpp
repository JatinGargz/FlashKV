#include "ThreadPool.h"

ThreadPool::ThreadPool(size_t threads) : stop(false) {
    if (threads == 0) threads = 1;
    for (size_t i = 0; i < threads; ++i) {
        workers.emplace_back([this]() {
            while (true) {
                std::function<void()> task;
                {
                    std::unique_lock<std::mutex> lock(this->queueMutex);
                    this->cv.wait(lock, [this]() {
                        return this->stop.load() || !this->tasks.empty();
                    });

                    if (this->stop.load() && this->tasks.empty()) {
                        return;
                    }

                    task = std::move(this->tasks.front());
                    this->tasks.pop();
                }
                task();
            }
        });
    }
}

ThreadPool::~ThreadPool() {
    stop.store(true);
    cv.notify_all();
    for (std::thread& worker : workers) {
        if (worker.joinable()) {
            worker.join();
        }
    }
}

void ThreadPool::enqueue(std::function<void()> task) {
    {
        std::unique_lock<std::mutex> lock(queueMutex);
        if (stop.load()) {
            return;
        }
        tasks.push(std::move(task));
    }
    cv.notify_one();
}
