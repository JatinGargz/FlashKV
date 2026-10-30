#include "StorageEngine.h"

int64_t StorageEngine::getNowEpochMs() {
    return std::chrono::duration_cast<std::chrono::milliseconds>(
        std::chrono::system_clock::now().time_since_epoch()
    ).count();
}

StorageEngine::StorageEngine(size_t capacity)
    : cache(capacity), cleanerRunning(true) {
    cleanerThread = std::thread(&StorageEngine::runActiveCleaner, this);
}

StorageEngine::~StorageEngine() {
    cleanerRunning = false;
    cleanerCv.notify_all();
    if (cleanerThread.joinable()) {
        cleanerThread.join();
    }
}

void StorageEngine::runActiveCleaner() {
    while (cleanerRunning) {
        {
            std::unique_lock<std::shared_mutex> lock(rwMutex);
            cleanerCv.wait_for(lock, std::chrono::seconds(1), [this]() {
                return !cleanerRunning.load();
            });

            if (!cleanerRunning) {
                break;
            }

            cache.purgeExpiredKeys(getNowEpochMs(), 100);
        }
    }
}

bool StorageEngine::set(const std::string& key, const std::string& value, int64_t ttlSeconds) {
    commandCount++;
    int64_t now = getNowEpochMs();
    int64_t expireAt = (ttlSeconds > 0) ? (now + ttlSeconds * 1000) : 0;

    std::unique_lock<std::shared_mutex> lock(rwMutex);
    return cache.put(key, value, expireAt);
}

bool StorageEngine::get(const std::string& key, std::string& outValue) {
    commandCount++;
    int64_t now = getNowEpochMs();

    std::unique_lock<std::shared_mutex> lock(rwMutex);
    bool found = cache.get(key, outValue, now);
    if (found) {
        hits++;
    } else {
        misses++;
    }
    return found;
}

bool StorageEngine::del(const std::string& key) {
    commandCount++;
    std::unique_lock<std::shared_mutex> lock(rwMutex);
    return cache.erase(key);
}

bool StorageEngine::exists(const std::string& key) {
    commandCount++;
    int64_t now = getNowEpochMs();

    std::unique_lock<std::shared_mutex> lock(rwMutex);
    return cache.exists(key, now);
}

int64_t StorageEngine::ttl(const std::string& key) {
    commandCount++;
    int64_t now = getNowEpochMs();

    std::unique_lock<std::shared_mutex> lock(rwMutex);
    return cache.getTTLSeconds(key, now);
}

void StorageEngine::flushDB() {
    commandCount++;
    std::unique_lock<std::shared_mutex> lock(rwMutex);
    cache.clear();
}

EngineStats StorageEngine::getStats() const {
    std::shared_lock<std::shared_mutex> lock(rwMutex);
    EngineStats st;
    st.keyCount = cache.size();
    st.capacity = cache.getCapacity();
    st.totalHits = hits.load();
    st.totalMisses = misses.load();
    st.totalCommands = commandCount.load();
    return st;
}

std::vector<std::string> StorageEngine::keys() {
    int64_t now = getNowEpochMs();
    std::unique_lock<std::shared_mutex> lock(rwMutex);
    return cache.getAllKeys(now);
}

std::vector<std::string> StorageEngine::lruOrder() {
    int64_t now = getNowEpochMs();
    std::unique_lock<std::shared_mutex> lock(rwMutex);
    return cache.getLRUOrder(now);
}

std::vector<std::pair<std::string, std::string>> StorageEngine::dump() {
    int64_t now = getNowEpochMs();
    std::unique_lock<std::shared_mutex> lock(rwMutex);
    return cache.dumpAll(now);
}
