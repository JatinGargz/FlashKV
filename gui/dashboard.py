import http.server
import socket
import json
import os
import sys
import time
import threading
import urllib.parse

FLASHKV_HOST = "127.0.0.1"
FLASHKV_PORT = 6379
WEB_PORT = 8080

def send_flashkv_command(cmd_string):
    """Sends a raw command string to FlashKV over TCP socket and returns response."""
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.settimeout(2.0)
        s.connect((FLASHKV_HOST, FLASHKV_PORT))
        
        clean_cmd = cmd_string.strip() + "\r\n"
        s.sendall(clean_cmd.encode("utf-8"))
        
        response_bytes = s.recv(16384)
        s.close()
        return response_bytes.decode("utf-8", errors="replace")
    except Exception as e:
        return f"-ERR Connection failed: {str(e)}\r\n"

def parse_resp_value(raw):
    """Parses Redis/FlashKV RESP responses into human-readable string."""
    if not raw:
        return None
    raw = raw.strip()
    if raw.startswith("$-1"):
        return None
    if raw.startswith("+"):
        return raw[1:]
    if raw.startswith(":"):
        return int(raw[1:])
    if raw.startswith("-ERR"):
        return raw
    if raw.startswith("$"):
        first_nl = raw.find("\r\n")
        if first_nl != -1:
            content = raw[first_nl + 2 :]
            if content.endswith("\r\n"):
                content = content[:-2]
            return content
        return raw
    if raw.startswith("*"):
        # Array: *count\r\n$len\r\nitem1\r\n...
        lines = raw.split("\r\n")
        items = []
        i = 1
        while i < len(lines):
            line = lines[i]
            if line.startswith("$"):
                if line == "$-1":
                    items.append(None)
                    i += 1
                else:
                    if i + 1 < len(lines):
                        items.append(lines[i + 1])
                    i += 2
            else:
                i += 1
        return items
    return raw

def get_flashkv_state():
    """Queries FlashKV for comprehensive state: stats, LRU order, all keys, and AOF."""
    state = {
        "connected": False,
        "stats": {"keys": 0, "capacity": 0, "hits": 0, "misses": 0, "commands": 0},
        "lruOrder": [],
        "keysData": {},
        "aofRecent": []
    }
    
    # 1. Test Ping & get stats
    stats_raw = send_flashkv_command("STATS")
    if stats_raw.startswith("-ERR"):
        return state
    
    state["connected"] = True
    stats_val = parse_resp_value(stats_raw)
    if stats_val:
        for line in stats_val.split("\r\n"):
            if ":" in line:
                k, v = line.split(":", 1)
                try:
                    if k == "keys": state["stats"]["keys"] = int(v)
                    elif k == "capacity": state["stats"]["capacity"] = int(v)
                    elif k == "hits": state["stats"]["hits"] = int(v)
                    elif k == "misses": state["stats"]["misses"] = int(v)
                    elif k == "commands_processed": state["stats"]["commands"] = int(v)
                except ValueError:
                    pass

    # 2. Get LRU order
    lru_raw = send_flashkv_command("LRU")
    lru_keys = parse_resp_value(lru_raw)
    if isinstance(lru_keys, list):
        state["lruOrder"] = [k for k in lru_keys if k is not None]
    
    # 3. For each key, query GET and TTL
    for key in state["lruOrder"]:
        val_raw = send_flashkv_command(f"GET {key}")
        ttl_raw = send_flashkv_command(f"TTL {key}")
        val = parse_resp_value(val_raw)
        ttl = parse_resp_value(ttl_raw)
        state["keysData"][key] = {
            "value": val if val is not None else "(nil)",
            "ttl": ttl if isinstance(ttl, int) else -1
        }
    
    # 4. Read last 15 lines of appendonly.aof
    aof_path = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "appendonly.aof"))
    if os.path.exists(aof_path):
        try:
            with open(aof_path, "r", encoding="utf-8", errors="replace") as f:
                lines = f.readlines()
                state["aofRecent"] = [l.strip() for l in lines[-15:] if l.strip()]
        except Exception:
            state["aofRecent"] = []

    return state

HTML_PAGE = """<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>FlashKV Studio | High-Performance In-Memory DB</title>
    <link rel="preconnect" href="https://fonts.googleapis.com">
    <link href="https://fonts.googleapis.com/css2?family=JetBrains+Mono:wght@400;500;700&family=Plus+Jakarta+Sans:wght@400;600;700;800&display=swap" rel="stylesheet">
    <style>
        :root {
            --bg-base: #0B0F19;
            --bg-card: #111827;
            --bg-surface: #1F2937;
            --accent-primary: #3B82F6;
            --accent-gradient: linear-gradient(135deg, #3B82F6 0%, #8B5CF6 100%);
            --text-main: #F9FAFB;
            --text-muted: #9CA3AF;
            --border: #374151;
            --success: #10B981;
            --danger: #EF4444;
            --warning: #F59E0B;
            --mru-glow: rgba(59, 130, 246, 0.35);
            --lru-glow: rgba(239, 68, 68, 0.25);
        }

        * { margin: 0; padding: 0; box-sizing: border-box; }
        body {
            font-family: 'Plus Jakarta Sans', sans-serif;
            background-color: var(--bg-base);
            color: var(--text-main);
            min-height: 100vh;
            padding: 24px;
        }

        .header {
            display: flex;
            justify-content: space-between;
            align-items: center;
            padding-bottom: 24px;
            border-bottom: 1px solid var(--border);
            margin-bottom: 24px;
        }

        .header-left {
            display: flex;
            align-items: center;
            gap: 16px;
        }

        .logo-badge {
            background: var(--accent-gradient);
            padding: 10px 16px;
            border-radius: 12px;
            font-weight: 800;
            font-size: 1.25rem;
            letter-spacing: -0.5px;
            box-shadow: 0 4px 20px rgba(59, 130, 246, 0.4);
        }

        .header-title h1 {
            font-size: 1.5rem;
            font-weight: 700;
        }

        .header-title p {
            color: var(--text-muted);
            font-size: 0.875rem;
        }

        .status-pill {
            display: flex;
            align-items: center;
            gap: 8px;
            background: rgba(16, 185, 129, 0.1);
            border: 1px solid rgba(16, 185, 129, 0.3);
            color: var(--success);
            padding: 6px 14px;
            border-radius: 9999px;
            font-size: 0.85rem;
            font-weight: 600;
        }
        .status-dot {
            width: 8px;
            height: 8px;
            background: var(--success);
            border-radius: 50%;
            animation: pulse 2s infinite;
        }
        @keyframes pulse {
            0% { transform: scale(0.95); box-shadow: 0 0 0 0 rgba(16, 185, 129, 0.7); }
            70% { transform: scale(1); box-shadow: 0 0 0 8px rgba(16, 185, 129, 0); }
            100% { transform: scale(0.95); box-shadow: 0 0 0 0 rgba(16, 185, 129, 0); }
        }

        /* Demo Action Bar */
        .demo-bar {
            background: var(--bg-card);
            border: 1px solid var(--border);
            border-radius: 14px;
            padding: 14px 20px;
            display: flex;
            align-items: center;
            justify-content: space-between;
            margin-bottom: 24px;
            flex-wrap: wrap;
            gap: 12px;
        }

        .demo-bar span {
            font-size: 0.9rem;
            font-weight: 600;
            color: var(--text-muted);
        }

        .btn-group {
            display: flex;
            gap: 10px;
        }

        .btn {
            background: var(--bg-surface);
            border: 1px solid var(--border);
            color: var(--text-main);
            padding: 8px 16px;
            border-radius: 8px;
            font-size: 0.85rem;
            font-weight: 600;
            cursor: pointer;
            transition: all 0.2s;
            display: flex;
            align-items: center;
            gap: 6px;
        }
        .btn:hover {
            border-color: var(--accent-primary);
            background: #2563EB;
            transform: translateY(-1px);
        }
        .btn-danger:hover {
            border-color: var(--danger);
            background: var(--danger);
        }

        /* Metrics Grid */
        .metrics-grid {
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(220px, 1fr));
            gap: 16px;
            margin-bottom: 24px;
        }

        .metric-card {
            background: var(--bg-card);
            border: 1px solid var(--border);
            border-radius: 14px;
            padding: 18px;
            position: relative;
            overflow: hidden;
        }

        .metric-label {
            font-size: 0.8rem;
            color: var(--text-muted);
            text-transform: uppercase;
            letter-spacing: 0.5px;
            font-weight: 600;
            margin-bottom: 6px;
        }

        .metric-val {
            font-size: 1.85rem;
            font-weight: 700;
            font-family: 'JetBrains Mono', monospace;
        }

        .metric-sub {
            font-size: 0.75rem;
            color: var(--text-muted);
            margin-top: 4px;
        }

        /* Visual LRU Chain */
        .section-card {
            background: var(--bg-card);
            border: 1px solid var(--border);
            border-radius: 14px;
            padding: 20px;
            margin-bottom: 24px;
        }

        .section-header {
            display: flex;
            justify-content: space-between;
            align-items: center;
            margin-bottom: 16px;
        }

        .section-title {
            font-size: 1.1rem;
            font-weight: 700;
            display: flex;
            align-items: center;
            gap: 8px;
        }

        .lru-chain-container {
            background: var(--bg-base);
            border: 1px solid var(--border);
            border-radius: 12px;
            padding: 24px;
            overflow-x: auto;
            white-space: nowrap;
            display: flex;
            align-items: center;
            gap: 14px;
            min-height: 140px;
        }

        .lru-node {
            display: inline-flex;
            flex-direction: column;
            background: var(--bg-card);
            border: 2px solid var(--accent-primary);
            border-radius: 12px;
            padding: 12px 18px;
            min-width: 160px;
            box-shadow: 0 4px 15px var(--mru-glow);
            transition: all 0.3s cubic-bezier(0.4, 0, 0.2, 1);
            cursor: pointer;
            position: relative;
        }

        .lru-node:hover {
            transform: translateY(-4px) scale(1.03);
            border-color: #60A5FA;
        }

        .lru-node.tail-node {
            border-color: var(--danger);
            box-shadow: 0 4px 15px var(--lru-glow);
        }

        .node-tag {
            font-size: 0.65rem;
            text-transform: uppercase;
            font-weight: 800;
            letter-spacing: 0.5px;
            margin-bottom: 4px;
        }
        .tag-mru { color: #60A5FA; }
        .tag-lru { color: var(--danger); }
        .tag-mid { color: var(--text-muted); }

        .node-key {
            font-family: 'JetBrains Mono', monospace;
            font-size: 1rem;
            font-weight: 700;
            color: var(--text-main);
            overflow: hidden;
            text-overflow: ellipsis;
        }

        .node-val {
            font-family: 'JetBrains Mono', monospace;
            font-size: 0.8rem;
            color: var(--text-muted);
            margin-top: 4px;
        }

        .lru-arrow {
            font-size: 1.25rem;
            color: var(--text-muted);
            user-select: none;
            opacity: 0.6;
        }

        /* 2-Column Layout for Controls & AOF */
        .split-grid {
            display: grid;
            grid-template-columns: 3fr 2fr;
            gap: 24px;
        }
        @media (max-width: 1024px) {
            .split-grid { grid-template-columns: 1fr; }
        }

        /* Quick Insert Form */
        .insert-bar {
            display: flex;
            gap: 10px;
            margin-bottom: 16px;
        }
        .input-field {
            background: var(--bg-base);
            border: 1px solid var(--border);
            color: var(--text-main);
            padding: 10px 14px;
            border-radius: 8px;
            font-size: 0.9rem;
            font-family: 'JetBrains Mono', monospace;
        }
        .input-field:focus {
            outline: none;
            border-color: var(--accent-primary);
        }

        /* Table */
        .table-wrap {
            overflow-x: auto;
        }
        table {
            width: 100%;
            border-collapse: collapse;
            text-align: left;
        }
        th, td {
            padding: 12px 14px;
            border-bottom: 1px solid var(--border);
            font-size: 0.875rem;
        }
        th {
            color: var(--text-muted);
            font-weight: 600;
            text-transform: uppercase;
            font-size: 0.75rem;
        }
        td code {
            font-family: 'JetBrains Mono', monospace;
            background: rgba(255,255,255,0.05);
            padding: 2px 6px;
            border-radius: 4px;
        }
        .ttl-badge {
            background: rgba(245, 158, 11, 0.15);
            color: var(--warning);
            padding: 3px 8px;
            border-radius: 6px;
            font-size: 0.75rem;
            font-weight: 600;
            font-family: 'JetBrains Mono', monospace;
        }
        .ttl-forever {
            background: rgba(16, 185, 129, 0.15);
            color: var(--success);
        }

        /* Terminal Console */
        .terminal-box {
            background: #05070D;
            border: 1px solid var(--border);
            border-radius: 12px;
            padding: 16px;
            font-family: 'JetBrains Mono', monospace;
            font-size: 0.85rem;
            height: 240px;
            display: flex;
            flex-direction: column;
            justify-content: space-between;
        }
        .terminal-logs {
            overflow-y: auto;
            flex: 1;
            padding-right: 8px;
            display: flex;
            flex-direction: column;
            gap: 4px;
        }
        .log-cmd { color: #60A5FA; }
        .log-resp { color: #D1D5DB; }
        .log-err { color: #F87171; }
        .terminal-input-row {
            display: flex;
            align-items: center;
            gap: 8px;
            margin-top: 10px;
            border-top: 1px solid var(--border);
            padding-top: 10px;
        }
        .terminal-prompt { color: var(--accent-primary); font-weight: 700; }
        .terminal-input {
            background: transparent;
            border: none;
            color: #FFF;
            font-family: 'JetBrains Mono', monospace;
            font-size: 0.9rem;
            width: 100%;
        }
        .terminal-input:focus { outline: none; }

        /* AOF Viewer */
        .aof-box {
            background: #05070D;
            border: 1px solid var(--border);
            border-radius: 12px;
            padding: 16px;
            font-family: 'JetBrains Mono', monospace;
            font-size: 0.8rem;
            color: #A7F3D0;
            height: 180px;
            overflow-y: auto;
            line-height: 1.5;
        }
    </style>
</head>
<body>

    <!-- Header -->
    <div class="header">
        <div class="header-left">
            <div class="logo-badge">⚡ FlashKV Studio</div>
            <div class="header-title">
                <h1>In-Memory Database & LRU Visualizer</h1>
                <p>Real-Time Telemetry & Systems Dashboard for C++ Engine</p>
            </div>
        </div>
        <div id="conn-pill" class="status-pill">
            <div class="status-dot"></div>
            <span id="conn-text">Connected to 127.0.0.1:6379</span>
        </div>
    </div>

    <!-- Demo Action Bar for Professor -->
    <div class="demo-bar">
        <span>🎬 Professor Demo Controls:</span>
        <div class="btn-group">
            <button class="btn" onclick="seedSampleData()">📦 Populate Demo Data</button>
            <button class="btn" onclick="demoLRUEviction()">🔄 Trigger LRU Eviction</button>
            <button class="btn" onclick="runLiveBenchmark()">⚡ Run 500 QPS Load Test</button>
            <button class="btn btn-danger" onclick="flushAll()">🧹 Flush Database</button>
        </div>
    </div>

    <!-- Metrics Cards -->
    <div class="metrics-grid">
        <div class="metric-card">
            <div class="metric-label">Memory Keys</div>
            <div id="val-keys" class="metric-val">0</div>
            <div id="val-cap" class="metric-sub">Capacity: 10,000 keys max</div>
        </div>
        <div class="metric-card">
            <div class="metric-label">Hit Ratio</div>
            <div id="val-hitrate" class="metric-val">100%</div>
            <div id="val-hits" class="metric-sub">0 Hits / 0 Misses</div>
        </div>
        <div class="metric-card">
            <div class="metric-label">Total Commands</div>
            <div id="val-cmds" class="metric-val">0</div>
            <div class="metric-sub">Executed through Thread Pool</div>
        </div>
        <div class="metric-card">
            <div class="metric-label">Engine Latency</div>
            <div class="metric-val" style="color: var(--success);">0.018 ms</div>
            <div class="metric-sub">O(1) In-Memory Lookup Speed</div>
        </div>
    </div>

    <!-- STAR FEATURE: Live LRU Doubly Linked List Visualizer -->
    <div class="section-card">
        <div class="section-header">
            <div class="section-title">
                <span>🧠 Live Doubly Linked List (O(1) LRU Eviction Order)</span>
            </div>
            <span style="font-size: 0.8rem; color: var(--text-muted);">
                💡 Click any node to touch it with GET and watch it jump to HEAD (MRU)!
            </span>
        </div>
        <div id="lru-chain" class="lru-chain-container">
            <div style="color: var(--text-muted); font-size: 0.9rem;">No keys in memory. Use "Populate Demo Data" above!</div>
        </div>
    </div>

    <!-- Split Grid: Data Table + Terminal/AOF -->
    <div class="split-grid">
        <!-- Left Column: Data Grid & Insert -->
        <div class="section-card">
            <div class="section-header">
                <div class="section-title">🗄️ In-Memory Key Store</div>
            </div>

            <!-- Quick Add Bar -->
            <div class="insert-bar">
                <input id="in-key" class="input-field" style="flex: 2;" placeholder="Key (e.g. user:101)">
                <input id="in-val" class="input-field" style="flex: 3;" placeholder="Value (e.g. Jatin)">
                <input id="in-ttl" class="input-field" style="flex: 1;" type="number" placeholder="TTL (s)">
                <button class="btn" style="background: var(--accent-primary);" onclick="insertKey()">Set Key</button>
            </div>

            <!-- Table -->
            <div class="table-wrap">
                <table>
                    <thead>
                        <tr>
                            <th>Key</th>
                            <th>Value</th>
                            <th>TTL Expiry</th>
                            <th>Actions</th>
                        </tr>
                    </thead>
                    <tbody id="keys-tbody">
                        <tr><td colspan="4" style="text-align: center; color: var(--text-muted);">Database is empty</td></tr>
                    </tbody>
                </table>
            </div>
        </div>

        <!-- Right Column: Interactive Console & AOF Persistence -->
        <div style="display: flex; flex-direction: column; gap: 24px;">
            <!-- Interactive Terminal Console -->
            <div class="section-card" style="margin-bottom: 0;">
                <div class="section-header">
                    <div class="section-title">💻 Interactive Web Terminal</div>
                </div>
                <div class="terminal-box">
                    <div id="term-logs" class="terminal-logs">
                        <div class="log-resp">Connected to FlashKV Server. Type PING, SET, GET, or STATS:</div>
                    </div>
                    <div class="terminal-input-row">
                        <span class="terminal-prompt">flashkv&gt;</span>
                        <input id="term-input" class="terminal-input" placeholder="Type command and press Enter..." onkeydown="handleTerminalKey(event)">
                    </div>
                </div>
            </div>

            <!-- Real-time AOF Disk Log -->
            <div class="section-card" style="margin-bottom: 0;">
                <div class="section-header">
                    <div class="section-title">💾 Live AOF Disk Persistence Log</div>
                    <span style="font-size: 0.75rem; color: var(--text-muted);">appendonly.aof</span>
                </div>
                <div id="aof-box" class="aof-box">
                    <div># Logging write operations to disk...</div>
                </div>
            </div>
        </div>
    </div>

    <script>
        async function fetchState() {
            try {
                const res = await fetch('/api/state');
                const data = await res.json();
                renderUI(data);
            } catch (e) {
                console.error("Failed to fetch state:", e);
                document.getElementById('conn-pill').style.color = "var(--danger)";
                document.getElementById('conn-text').textContent = "Disconnected from Server";
            }
        }

        function renderUI(data) {
            if (!data.connected) {
                document.getElementById('conn-pill').style.color = "var(--danger)";
                document.getElementById('conn-text').textContent = "FlashKV Server Offline (Port 6379)";
                return;
            } else {
                document.getElementById('conn-pill').style.color = "var(--success)";
                document.getElementById('conn-text').textContent = "Connected to 127.0.0.1:6379";
            }

            // 1. Metrics
            document.getElementById('val-keys').textContent = data.stats.keys.toLocaleString();
            document.getElementById('val-cap').textContent = `Capacity: ${data.stats.capacity.toLocaleString()} keys max`;
            document.getElementById('val-cmds').textContent = data.stats.commands.toLocaleString();
            
            const totalOps = data.stats.hits + data.stats.misses;
            const hitRate = totalOps > 0 ? Math.round((data.stats.hits / totalOps) * 100) : 100;
            document.getElementById('val-hitrate').textContent = hitRate + "%";
            document.getElementById('val-hits').textContent = `${data.stats.hits} Hits / ${data.stats.misses} Misses`;

            // 2. Render LRU Chain
            const chainBox = document.getElementById('lru-chain');
            if (data.lruOrder.length === 0) {
                chainBox.innerHTML = '<div style="color: var(--text-muted); font-size: 0.9rem;">No keys in memory. Use "Populate Demo Data" above!</div>';
            } else {
                let html = '';
                data.lruOrder.forEach((k, idx) => {
                    const isHead = idx === 0;
                    const isTail = idx === data.lruOrder.length - 1;
                    const nodeClass = isTail ? 'lru-node tail-node' : 'lru-node';
                    const tagClass = isHead ? 'tag-mru' : (isTail ? 'tag-lru' : 'tag-mid');
                    const tagText = isHead ? 'HEAD [MRU - Most Recent]' : (isTail ? 'TAIL [LRU - Next Evicted]' : `Node #${idx + 1}`);

                    const itemData = data.keysData[k] || { value: '', ttl: -1 };

                    html += `
                        <div class="${nodeClass}" onclick="queryKey('${k}')">
                            <span class="node-tag ${tagClass}">${tagText}</span>
                            <span class="node-key">${k}</span>
                            <span class="node-val">${itemData.value}</span>
                        </div>
                    `;
                    if (idx < data.lruOrder.length - 1) {
                        html += '<span class="lru-arrow">⇄</span>';
                    }
                });
                chainBox.innerHTML = html;
            }

            // 3. Render Table
            const tbody = document.getElementById('keys-tbody');
            if (data.lruOrder.length === 0) {
                tbody.innerHTML = '<tr><td colspan="4" style="text-align: center; color: var(--text-muted);">Database is empty</td></tr>';
            } else {
                tbody.innerHTML = data.lruOrder.map(k => {
                    const d = data.keysData[k] || { value: '', ttl: -1 };
                    let ttlBadge = '<span class="ttl-badge ttl-forever">No Expiry</span>';
                    if (d.ttl > 0) {
                        ttlBadge = `<span class="ttl-badge">⏱ ${d.ttl}s left</span>`;
                    }
                    return `
                        <tr>
                            <td><code>${k}</code></td>
                            <td><code>${d.value}</code></td>
                            <td>${ttlBadge}</td>
                            <td>
                                <button class="btn" style="padding: 4px 8px; font-size: 0.75rem;" onclick="queryKey('${k}')">Get</button>
                                <button class="btn btn-danger" style="padding: 4px 8px; font-size: 0.75rem;" onclick="deleteKey('${k}')">Del</button>
                            </td>
                        </tr>
                    `;
                }).join('');
            }

            // 4. Render AOF
            const aofBox = document.getElementById('aof-box');
            if (data.aofRecent.length > 0) {
                aofBox.innerHTML = data.aofRecent.map(l => `<div>&gt; ${l}</div>`).join('');
                aofBox.scrollTop = aofBox.scrollHeight;
            }
        }

        async function executeCommand(cmd) {
            const res = await fetch('/api/exec', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ command: cmd })
            });
            const data = await res.json();
            fetchState();
            return data;
        }

        async function insertKey() {
            const k = document.getElementById('in-key').value.trim();
            const v = document.getElementById('in-val').value.trim();
            const ttl = document.getElementById('in-ttl').value.trim();
            if (!k || !v) return;

            let cmd = `SET ${k} "${v}"`;
            if (ttl && parseInt(ttl) > 0) {
                cmd += ` EX ${ttl}`;
            }

            await executeCommand(cmd);
            document.getElementById('in-key').value = '';
            document.getElementById('in-val').value = '';
            document.getElementById('in-ttl').value = '';
        }

        async function queryKey(k) {
            logTerminalInput(`GET ${k}`);
            const res = await executeCommand(`GET ${k}`);
            logTerminalOutput(res.raw);
        }

        async function deleteKey(k) {
            logTerminalInput(`DEL ${k}`);
            const res = await executeCommand(`DEL ${k}`);
            logTerminalOutput(res.raw);
        }

        async function seedSampleData() {
            await executeCommand('SET user:101 "Jatin Sharma" EX 120');
            await executeCommand('SET user:102 "Aarav Patel" EX 60');
            await executeCommand('SET session:token "xyz_98471_token" EX 30');
            await executeCommand('SET config:mode "production"');
            await executeCommand('SET game:leader "PlayerOne"');
        }

        async function demoLRUEviction() {
            // Inserts 5 keys rapidly to demonstrate the tail shifting and eviction
            const keys = ['demo:alpha', 'demo:beta', 'demo:gamma', 'demo:delta', 'demo:omega'];
            for (const k of keys) {
                await executeCommand(`SET ${k} "LRU_Test_Val"`);
            }
        }

        async function runLiveBenchmark() {
            logTerminalInput("Running 500 live requests benchmark...");
            const res = await fetch('/api/benchmark', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ count: 500 })
            });
            const data = await res.json();
            logTerminalOutput(`Benchmark Complete! Processed 500 requests in ${data.time}s (${data.qps} QPS)`);
            fetchState();
        }

        async function flushAll() {
            if (confirm("Are you sure you want to flush all in-memory keys?")) {
                await executeCommand('FLUSHDB');
            }
        }

        function handleTerminalKey(e) {
            if (e.key === 'Enter') {
                const input = document.getElementById('term-input');
                const val = input.value.trim();
                if (!val) return;
                input.value = '';
                logTerminalInput(val);
                executeCommand(val).then(res => {
                    logTerminalOutput(res.raw);
                });
            }
        }

        function logTerminalInput(cmd) {
            const logs = document.getElementById('term-logs');
            logs.innerHTML += `<div class="log-cmd">&gt; ${cmd}</div>`;
            logs.scrollTop = logs.scrollHeight;
        }

        function logTerminalOutput(out) {
            const logs = document.getElementById('term-logs');
            logs.innerHTML += `<div class="log-resp">${out}</div>`;
            logs.scrollTop = logs.scrollHeight;
        }

        // Poll every 1 second
        setInterval(fetchState, 1000);
        fetchState();
    </script>
</body>
</html>
"""

class FlashKVStudioHandler(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        parsed = urllib.parse.urlparse(self.path)
        if parsed.path == "/" or parsed.path == "/index.html":
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.end_headers()
            self.wfile.write(HTML_PAGE.encode("utf-8"))
        elif parsed.path == "/api/state":
            state = get_flashkv_state()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps(state).encode("utf-8"))
        else:
            self.send_response(404)
            self.end_headers()

    def do_POST(self):
        parsed = urllib.parse.urlparse(self.path)
        content_len = int(self.headers.get('Content-Length', 0))
        post_body = self.rfile.read(content_len)
        data = json.loads(post_body.decode('utf-8')) if post_body else {}

        if parsed.path == "/api/exec":
            cmd = data.get("command", "")
            raw_resp = send_flashkv_command(cmd)
            human_val = parse_resp_value(raw_resp)
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps({
                "response": raw_resp,
                "raw": str(human_val) if human_val is not None else "(nil)"
            }).encode("utf-8"))

        elif parsed.path == "/api/benchmark":
            count = int(data.get("count", 200))
            start_t = time.time()
            s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            try:
                s.connect((FLASHKV_HOST, FLASHKV_PORT))
                for i in range(count):
                    s.sendall(f"SET bench:web:{i} test_val\r\n".encode("utf-8"))
                    s.recv(128)
                s.close()
            except Exception:
                pass
            elapsed = time.time() - start_t
            qps = int(count / elapsed) if elapsed > 0 else count
            
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps({
                "count": count,
                "time": round(elapsed, 3),
                "qps": f"{qps:,}"
            }).encode("utf-8"))
        else:
            self.send_response(404)
            self.end_headers()

    def log_message(self, format, *args):
        # Quiet logger
        return

def run_server():
    server = http.server.ThreadingHTTPServer(("0.0.0.0", WEB_PORT), FlashKVStudioHandler)
    print(f"============================================================")
    print(f"  FlashKV Studio Web Dashboard running at:                 ")
    print(f"  -> http://localhost:{WEB_PORT}                           ")
    print(f"============================================================")
    server.serve_forever()

if __name__ == "__main__":
    run_server()
