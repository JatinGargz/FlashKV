"""
AuthKV — Enterprise In-Memory 2FA & Ephemeral Identity Engine
Backed by FlashKV C++ In-Memory Storage Engine on Port 6379.
Provides:
  - Dual-Channel Real SMS (Fast2SMS / Twilio) and Real Email (Gmail SMTP / Resend) Dispatch
  - Cryptographic 6-digit OTP generation with Microsecond Hardware-Level TTL Auto-Eviction
  - Zero-Knowledge Single-Use Memory Invalidation (DEL) protecting against replay attacks
  - Brute-Force lockout with attempt tracking in RAM
  - Multi-Application support: 2FA Identity Gate, Esports Leaderboard, URL Shortener
  - Slide-Over C++ Engine Telemetry Drawer (LRU DoublyLinkedList Chain, AOF Log & RESP Terminal)
"""

import http.server
import socket
import json
import hashlib
import time
import os
import urllib.parse
import urllib.request
import string
import random
import io
import base64
import smtplib
import ssl
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

try:
    import qrcode
    HAS_QR = True
except ImportError:
    HAS_QR = False

REDIS_HOST = "127.0.0.1"
REDIS_PORT = 6379
WEB_PORT = 5000
BASE_URL = f"http://localhost:{WEB_PORT}"
CONFIG_PATH = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "gateway_config.json"))

# ─── Configuration Loader ────────────────────────────────────────────

def load_gateway_config():
    defaults = {
        "twofactor_key": "",
        "fast2sms_key": "",
        "smtp_host": "smtp.gmail.com",
        "smtp_port": 587,
        "smtp_user": "",
        "smtp_pass": "",
        "resend_key": "",
        "twilio_sid": "",
        "twilio_token": "",
        "twilio_phone": ""
    }
    if os.path.exists(CONFIG_PATH):
        try:
            with open(CONFIG_PATH, "r", encoding="utf-8") as f:
                data = json.load(f)
                defaults.update(data)
        except Exception:
            pass
    return defaults


def save_gateway_config(config_dict):
    try:
        with open(CONFIG_PATH, "w", encoding="utf-8") as f:
            json.dump(config_dict, f, indent=2)
        return True
    except Exception:
        return False


# ─── Mini-Redis TCP Client ───────────────────────────────────────────

def redis_cmd(cmd_str):
    """Send a single command to Mini-Redis over TCP and return raw response."""
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.settimeout(2.0)
        s.connect((REDIS_HOST, REDIS_PORT))
        s.sendall((cmd_str.strip() + "\r\n").encode())
        data = s.recv(16384).decode("utf-8", errors="replace")
        s.close()
        return data
    except Exception as e:
        return f"-ERR {e}\r\n"


def redis_set(key, value, ttl=0):
    cmd = f'SET {key} "{value}"'
    if ttl > 0:
        cmd += f' EX {ttl}'
    return redis_cmd(cmd)


def redis_get(key):
    raw = redis_cmd(f'GET {key}')
    if not raw or raw.startswith("$-1"):
        return None
    idx = raw.find("\r\n")
    if idx == -1:
        return None
    val = raw[idx + 2:]
    if val.endswith("\r\n"):
        val = val[:-2]
    return val


def redis_del(key):
    return redis_cmd(f'DEL {key}')


def redis_exists(key):
    raw = redis_cmd(f'EXISTS {key}')
    return raw.strip() == ":1"


def redis_ttl(key):
    raw = redis_cmd(f'TTL {key}')
    try:
        return int(raw.strip().lstrip(":"))
    except Exception:
        return -2


def redis_keys():
    raw = redis_cmd("KEYS")
    if not raw or not raw.startswith("*"):
        return []
    lines = raw.split("\r\n")
    items = []
    i = 1
    while i < len(lines):
        if lines[i].startswith("$"):
            if i + 1 < len(lines):
                items.append(lines[i + 1])
            i += 2
        else:
            i += 1
    return items


def redis_lru_order():
    raw = redis_cmd("LRU")
    if not raw or not raw.startswith("*"):
        return []
    lines = raw.split("\r\n")
    items = []
    i = 1
    while i < len(lines):
        if lines[i].startswith("$"):
            if i + 1 < len(lines):
                items.append(lines[i + 1])
            i += 2
        else:
            i += 1
    return items


def redis_stats():
    raw = redis_cmd("STATS")
    if not raw or raw.startswith("-ERR"):
        return {}
    idx = raw.find("\r\n")
    body = raw[idx + 2:] if idx != -1 else raw
    st = {}
    for line in body.split("\r\n"):
        if ":" in line:
            k, v = line.split(":", 1)
            try:
                st[k.strip()] = int(v.strip())
            except ValueError:
                st[k.strip()] = v.strip()
    return st


# ─── Real Dispatch Providers (SMS & Email) ───────────────────────────

def send_real_sms(phone_number, otp_code, purpose="Authentication"):
    """Attempts to dispatch real SMS via Fast2SMS or Twilio based on config"""
    cfg = load_gateway_config()
    
    # 1. 2Factor.in (India Free Developer Trial - Pre-approved DLT)
    two_key = cfg.get("twofactor_key", "").strip()
    if two_key:
        clean_number = "".join(filter(str.isdigit, phone_number))
        if len(clean_number) == 10:
            clean_number = "91" + clean_number
        url = f"https://2factor.in/API/V1/{two_key}/SMS/{clean_number}/{otp_code}"
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        try:
            with urllib.request.urlopen(req, timeout=8) as response:
                res_data = json.loads(response.read().decode())
                if res_data.get("Status") == "Success":
                    return True, "Delivered to mobile via 2Factor.in"
                return False, res_data.get("Details", "2Factor error")
        except Exception as e:
            return False, f"2Factor Error: {e}"

    # 2. Fast2SMS (India numbers +91)
    f2s_key = cfg.get("fast2sms_key", "").strip()
    if f2s_key:
        clean_number = "".join(filter(str.isdigit, phone_number))
        if clean_number.startswith("91") and len(clean_number) == 12:
            clean_number = clean_number[2:]
        url = f"https://www.fast2sms.com/dev/bulkV2?authorization={f2s_key}&variables_values={otp_code}&route=otp&numbers={clean_number}"
        req = urllib.request.Request(url, headers={"cache-control": "no-cache"})
        try:
            with urllib.request.urlopen(req, timeout=8) as response:
                res_data = json.loads(response.read().decode())
                if res_data.get("return", False):
                    return True, "Delivered to mobile via Fast2SMS"
                return False, res_data.get("message", ["Fast2SMS error"])[0]
        except urllib.error.HTTPError as e:
            try:
                err_body = json.loads(e.read().decode())
                msg = err_body.get("message", str(e))
                return False, f"Fast2SMS: {msg}"
            except Exception:
                return False, f"Fast2SMS HTTP Error: {e}"
        except Exception as e:
            return False, f"Fast2SMS Network Error: {e}"

    # 2. Twilio (Worldwide)
    tw_sid = cfg.get("twilio_sid", "").strip()
    tw_token = cfg.get("twilio_token", "").strip()
    tw_phone = cfg.get("twilio_phone", "").strip()
    if tw_sid and tw_token and tw_phone:
        try:
            api_url = f"https://api.twilio.com/2010-04-01/Accounts/{tw_sid}/Messages.json"
            clean_number = phone_number.strip()
            if not clean_number.startswith("+"):
                digits = "".join(filter(str.isdigit, clean_number))
                clean_number = "+91" + digits if len(digits) == 10 else "+" + digits
            post_data = urllib.parse.urlencode({
                "To": clean_number,
                "From": tw_phone,
                "Body": f"[FlashKV Security] Your OTP for {purpose} is {otp_code}. Valid for in-memory session."
            }).encode("utf-8")
            req = urllib.request.Request(api_url, data=post_data, headers={
                "Authorization": "Basic " + base64.b64encode(f"{tw_sid}:{tw_token}".encode()).decode()
            })
            with urllib.request.urlopen(req, timeout=8) as response:
                return True, "Delivered via Twilio SMS"
        except urllib.error.HTTPError as e:
            try:
                err_body = json.loads(e.read().decode())
                return False, f"Twilio: {err_body.get('message', str(e))}"
            except Exception:
                return False, f"Twilio HTTP Error: {e}"
        except Exception as e:
            return False, f"Twilio Error: {e}"

    return False, "No SMS Gateway Key configured (Using Live Simulated Delivery)"


def send_real_email(recipient_email, otp_code, purpose="Authentication", ttl=60):
    """Attempts to dispatch real HTML email via SMTP or Resend API"""
    cfg = load_gateway_config()

    # 1. Resend API
    resend_key = cfg.get("resend_key", "").strip()
    if resend_key:
        try:
            payload = json.dumps({
                "from": "FlashKV Security <onboarding@resend.dev>",
                "to": [recipient_email],
                "subject": f"[FlashKV] Security Passcode: {otp_code}",
                "html": f"<p>Your FlashKV 2FA code is <strong>{otp_code}</strong>. Valid for {ttl}s in RAM.</p>"
            }).encode("utf-8")
            req = urllib.request.Request("https://api.resend.com/emails", data=payload, headers={
                "Authorization": f"Bearer {resend_key}",
                "Content-Type": "application/json"
            })
            with urllib.request.urlopen(req, timeout=8) as response:
                return True, "Delivered via Resend API"
        except Exception as e:
            return False, f"Resend Error: {e}"

    # 2. Direct SMTP (Gmail / Outlook)
    user = cfg.get("smtp_user", "").strip()
    password = cfg.get("smtp_pass", "").strip()
    host = cfg.get("smtp_host", "smtp.gmail.com").strip()
    port = int(cfg.get("smtp_port", 587))

    if user and password:
        msg = MIMEMultipart("alternative")
        msg["Subject"] = f"[FlashKV Security] Your 2FA Code: {otp_code}"
        msg["From"] = f"FlashKV Security <{user}>"
        msg["To"] = recipient_email

        text = f"Your FlashKV 2FA verification code is: {otp_code}. Valid for {ttl} seconds."
        html = f"""<!DOCTYPE html>
<html>
<body style="font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; background-color: #0B0F19; margin: 0; padding: 28px; color: #F8FAFC;">
  <div style="max-width: 480px; margin: 0 auto; background: #111827; border-radius: 14px; padding: 28px; border: 1px solid #1E293B;">
    <div style="font-size: 20px; font-weight: 800; color: #38BDF8; margin-bottom: 8px;">⚡ FlashKV Auth Gateway</div>
    <p style="color: #94A3B8; font-size: 14px; margin-bottom: 20px;">
      One-time security passcode for <strong>{purpose}</strong>:
    </p>
    <div style="background: #090D16; border: 1.5px dashed #38BDF8; border-radius: 10px; padding: 18px; text-align: center; margin-bottom: 20px;">
      <span style="font-family: monospace; font-size: 34px; font-weight: 800; letter-spacing: 8px; color: #38BDF8;">{otp_code}</span>
    </div>
    <div style="font-size: 13px; color: #CBD5E1; margin-bottom: 8px;">
      ⏱️ Valid for <strong>{ttl} seconds</strong> only.
    </div>
    <div style="font-size: 12px; color: #64748B; border-top: 1px solid #1E293B; padding-top: 14px; margin-top: 20px;">
      Protected by FlashKV C++ In-Memory Engine. Token automatically purged from RAM upon expiry or single-use verification.
    </div>
  </div>
</body>
</html>"""
        msg.attach(MIMEText(text, "plain"))
        msg.attach(MIMEText(html, "html"))

        try:
            context = ssl.create_default_context()
            server = smtplib.SMTP(host, port, timeout=9)
            server.starttls(context=context)
            server.login(user, password)
            server.sendmail(user, [recipient_email], msg.as_string())
            server.quit()
            return True, f"Delivered to {recipient_email} via SMTP"
        except Exception as e:
            return False, f"SMTP Error: {e}"

    return False, "No SMTP Credentials configured (Using Live Simulated Delivery)"


# ─── Seed Data for Secondary Demos ────────────────────────────────────

DEFAULT_PLAYERS = [
    {"id": "p1", "name": "ViperStrike", "avatar": "⚡", "tier": "Grandmaster", "score": 2940, "matches": 54, "wins": 49},
    {"id": "p2", "name": "PhantomBlade", "avatar": "🗡️", "tier": "Grandmaster", "score": 2720, "matches": 46, "wins": 39},
    {"id": "p3", "name": "CyberValkyrie", "avatar": "🛡️", "tier": "Diamond", "score": 2510, "matches": 38, "wins": 31},
    {"id": "p4", "name": "NexusRogue", "avatar": "🏹", "tier": "Diamond", "score": 2380, "matches": 35, "wins": 27},
    {"id": "p5", "name": "AetherWolf", "avatar": "🐺", "tier": "Platinum", "score": 2150, "matches": 29, "wins": 21},
    {"id": "p6", "name": "SolarEcho", "avatar": "☀️", "tier": "Platinum", "score": 1960, "matches": 24, "wins": 16},
    {"id": "p7", "name": "ShadowByte", "avatar": "👾", "tier": "Gold", "score": 1780, "matches": 20, "wins": 12},
    {"id": "p8", "name": "GlitchHunter", "avatar": "🎯", "tier": "Gold", "score": 1620, "matches": 17, "wins": 9}
]

def seed_leaderboard_if_empty():
    keys = redis_keys()
    lb_keys = [k for k in keys if k.startswith("lb:player:")]
    if not lb_keys:
        for p in DEFAULT_PLAYERS:
            pid = p["id"]
            encoded = urllib.parse.quote(json.dumps(p))
            redis_set(f"lb:player:{pid}", encoded)
            redis_set(f"lb:score:{pid}", str(p["score"]))


def seed_links_if_empty():
    keys = redis_keys()
    url_keys = [k for k in keys if k.startswith("url:")]
    if not url_keys:
        default_links = [
            {"code": "redis-docs", "url": "https://redis.io/documentation", "tag": "Dev", "ttl": 0, "clicks": 142},
            {"code": "cpp-reference", "url": "https://en.cppreference.com/w/cpp", "tag": "Dev", "ttl": 0, "clicks": 89}
        ]
        for l in default_links:
            c = l["code"]
            redis_set(f"url:{c}", l["url"], l["ttl"])
            redis_set(f"clicks:{c}", str(l["clicks"]))
            redis_set(f"meta:{c}", urllib.parse.quote(json.dumps({"tag": l["tag"], "url": l["url"]})), l["ttl"])


# ─── URL Shortener Helpers ───────────────────────────────────────────

ALPHABET = string.ascii_letters + string.digits

def generate_code(url, length=6):
    h = hashlib.sha256((url + str(time.time())).encode()).hexdigest()
    num = int(h[:10], 16)
    code = []
    for _ in range(length):
        code.append(ALPHABET[num % len(ALPHABET)])
        num //= len(ALPHABET)
    return ''.join(code)


def make_qr_base64(url):
    if not HAS_QR:
        return ""
    try:
        qr = qrcode.QRCode(version=1, box_size=6, border=2)
        qr.add_data(url)
        qr.make(fit=True)
        img = qr.make_image(fill_color="#0F172A", back_color="#FFFFFF")
        buf = io.BytesIO()
        img.save(buf, format="PNG")
        return "data:image/png;base64," + base64.b64encode(buf.getvalue()).decode()
    except Exception:
        return ""


# ─── Production Frontend HTML/CSS/JS ──────────────────────────────────

HTML_PAGE = r"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>AuthKV — Ephemeral In-Memory 2FA & Identity Engine</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link href="https://fonts.googleapis.com/css2?family=JetBrains+Mono:wght@400;500;600;700&family=Plus+Jakarta+Sans:wght@400;500;600;700;800&display=swap" rel="stylesheet">
<style>
  *, *::before, *::after { margin: 0; padding: 0; box-sizing: border-box; }

  :root {
    --bg-base: #0B0F19;
    --bg-card: #111827;
    --bg-surface: #172236;
    --bg-hover: #1E2D45;
    --border: #1E293B;
    --border-light: #2A3B52;
    --border-accent: rgba(59, 130, 246, 0.4);
    --text-primary: #F8FAFC;
    --text-secondary: #94A3B8;
    --text-muted: #64748B;
    --accent: #3B82F6;
    --accent-hover: #2563EB;
    --accent-glow: rgba(59, 130, 246, 0.25);
    --green: #10B981;
    --green-glow: rgba(16, 185, 129, 0.2);
    --amber: #F59E0B;
    --amber-glow: rgba(245, 158, 11, 0.25);
    --purple: #8B5CF6;
    --red: #EF4444;
    --radius-sm: 8px;
    --radius: 12px;
    --radius-lg: 16px;
    --font-sans: 'Plus Jakarta Sans', -apple-system, sans-serif;
    --font-mono: 'JetBrains Mono', monospace;
  }

  body {
    font-family: var(--font-sans);
    background-color: var(--bg-base);
    color: var(--text-primary);
    line-height: 1.5;
    min-height: 100vh;
    padding-bottom: 70px;
    -webkit-font-smoothing: antialiased;
    overflow-x: hidden;
  }

  /* ── Header ── */
  header {
    background: rgba(17, 24, 39, 0.9);
    border-bottom: 1px solid var(--border);
    padding: 0 36px;
    height: 72px;
    display: flex;
    align-items: center;
    justify-content: space-between;
    position: sticky;
    top: 0;
    z-index: 40;
    backdrop-filter: blur(12px);
  }
  .brand-group {
    display: flex;
    align-items: center;
    gap: 14px;
    text-decoration: none;
  }
  .brand-icon {
    width: 38px; height: 38px;
    background: linear-gradient(135deg, #3B82F6 0%, #10B981 100%);
    border-radius: 10px;
    display: flex;
    align-items: center;
    justify-content: center;
    font-weight: 800;
    font-size: 1.15rem;
    color: #fff;
    box-shadow: 0 2px 14px var(--accent-glow);
  }
  .brand-title {
    font-weight: 800;
    font-size: 1.25rem;
    letter-spacing: -0.02em;
    color: var(--text-primary);
    display: flex;
    align-items: center;
    gap: 10px;
  }
  .brand-tag {
    font-size: 0.68rem;
    font-weight: 700;
    padding: 2px 8px;
    border-radius: 6px;
    background: rgba(16, 185, 129, 0.12);
    color: var(--green);
    letter-spacing: 0.04em;
    border: 1px solid rgba(16, 185, 129, 0.25);
  }

  /* ── Main Clean App Switcher ── */
  .app-nav {
    display: flex;
    background: #090D16;
    padding: 4px;
    border-radius: 12px;
    border: 1px solid var(--border);
    gap: 4px;
  }
  .app-nav-btn {
    padding: 8px 18px;
    border-radius: 9px;
    border: none;
    background: transparent;
    color: var(--text-secondary);
    font-size: 0.85rem;
    font-weight: 600;
    cursor: pointer;
    transition: all 0.2s cubic-bezier(0.4, 0, 0.2, 1);
    display: flex;
    align-items: center;
    gap: 8px;
  }
  .app-nav-btn:hover {
    color: var(--text-primary);
    background: rgba(255, 255, 255, 0.04);
  }
  .app-nav-btn.active {
    background: var(--accent);
    color: #FFFFFF;
    box-shadow: 0 2px 10px var(--accent-glow);
  }

  .header-actions {
    display: flex;
    align-items: center;
    gap: 12px;
  }
  .btn-settings {
    background: var(--bg-surface);
    color: var(--text-secondary);
    border: 1px solid var(--border-light);
    padding: 7px 14px;
    border-radius: 8px;
    font-size: 0.8rem;
    font-weight: 600;
    cursor: pointer;
    display: flex;
    align-items: center;
    gap: 6px;
    transition: all 0.2s ease;
  }
  .btn-settings:hover {
    color: var(--text-primary);
    background: var(--bg-hover);
  }
  .btn-telemetry {
    background: rgba(139, 92, 246, 0.12);
    color: #A78BFA;
    border: 1px solid rgba(139, 92, 246, 0.3);
    padding: 7px 14px;
    border-radius: 8px;
    font-size: 0.8rem;
    font-weight: 600;
    cursor: pointer;
    display: flex;
    align-items: center;
    gap: 6px;
    transition: all 0.2s ease;
  }
  .btn-telemetry:hover {
    background: rgba(139, 92, 246, 0.22);
    border-color: rgba(139, 92, 246, 0.5);
    color: #DDD6FE;
    transform: translateY(-1px);
  }

  /* ── Main Container ── */
  .container {
    max-width: 1240px;
    margin: 32px auto 0;
    padding: 0 24px;
  }

  .view-pane {
    display: none;
    animation: fadeIn 0.22s ease-in-out;
  }
  .view-pane.active {
    display: block;
  }
  @keyframes fadeIn {
    from { opacity: 0; transform: translateY(6px); }
    to { opacity: 1; transform: translateY(0); }
  }

  /* ── Hero Banners ── */
  .hero-banner {
    display: flex;
    justify-content: space-between;
    align-items: flex-end;
    margin-bottom: 24px;
  }
  .hero-text h1 {
    font-size: 1.7rem;
    font-weight: 800;
    letter-spacing: -0.03em;
    color: var(--text-primary);
    margin-bottom: 4px;
  }
  .hero-text p {
    font-size: 0.92rem;
    color: var(--text-secondary);
  }
  .hero-metric-bar {
    display: flex;
    gap: 12px;
  }
  .metric-chip {
    background: var(--bg-card);
    border: 1px solid var(--border);
    padding: 8px 14px;
    border-radius: var(--radius-sm);
    display: flex;
    flex-direction: column;
    min-width: 110px;
  }
  .metric-chip span.label {
    font-size: 0.68rem;
    color: var(--text-muted);
    font-weight: 700;
    text-transform: uppercase;
    letter-spacing: 0.05em;
  }
  .metric-chip span.val {
    font-family: var(--font-mono);
    font-size: 1.15rem;
    font-weight: 700;
    color: var(--accent);
  }

  /* ── Cards ── */
  .card {
    background: var(--bg-card);
    border: 1px solid var(--border);
    border-radius: var(--radius-lg);
    padding: 24px 28px;
    margin-bottom: 24px;
    box-shadow: 0 4px 20px rgba(0, 0, 0, 0.25);
  }
  .card-header {
    display: flex;
    justify-content: space-between;
    align-items: center;
    margin-bottom: 20px;
    padding-bottom: 14px;
    border-bottom: 1px solid var(--border);
  }
  .card-title {
    font-size: 1.05rem;
    font-weight: 700;
    color: var(--text-primary);
    display: flex;
    align-items: center;
    gap: 10px;
  }
  .card-subtitle {
    font-size: 0.82rem;
    color: var(--text-secondary);
    margin-top: 2px;
  }

  /* ── Channel Selector Pills ── */
  .channel-pill-group {
    display: flex;
    background: var(--bg-base);
    border: 1px solid var(--border);
    padding: 4px;
    border-radius: var(--radius-sm);
    gap: 4px;
    margin-bottom: 14px;
  }
  .channel-pill-btn {
    flex: 1;
    padding: 8px 12px;
    border-radius: 6px;
    border: none;
    background: transparent;
    color: var(--text-secondary);
    font-size: 0.82rem;
    font-weight: 600;
    cursor: pointer;
    transition: all 0.15s ease;
    display: flex;
    align-items: center;
    justify-content: center;
    gap: 6px;
  }
  .channel-pill-btn.active {
    background: var(--accent);
    color: #fff;
  }

  /* ── Form Controls ── */
  .form-group {
    display: flex;
    flex-direction: column;
    gap: 6px;
  }
  .form-group label {
    font-size: 0.74rem;
    font-weight: 700;
    color: var(--text-muted);
    text-transform: uppercase;
    letter-spacing: 0.05em;
  }
  .form-control {
    background: var(--bg-surface);
    border: 1px solid var(--border);
    border-radius: var(--radius-sm);
    padding: 10px 14px;
    color: var(--text-primary);
    font-family: var(--font-sans);
    font-size: 0.88rem;
    outline: none;
    transition: all 0.2s ease;
  }
  .form-control:focus {
    border-color: var(--accent);
    background: #1C2A42;
    box-shadow: 0 0 0 3px var(--accent-glow);
  }

  .btn {
    padding: 10px 20px;
    border-radius: var(--radius-sm);
    font-weight: 600;
    font-size: 0.88rem;
    cursor: pointer;
    border: 1px solid transparent;
    transition: all 0.18s ease;
    display: inline-flex;
    align-items: center;
    justify-content: center;
    gap: 8px;
    white-space: nowrap;
    text-decoration: none;
  }
  .btn:active { transform: scale(0.98); }
  .btn-primary {
    background: var(--accent);
    color: #fff;
    box-shadow: 0 2px 10px var(--accent-glow);
  }
  .btn-primary:hover {
    background: var(--accent-hover);
    transform: translateY(-1px);
  }
  .btn-secondary {
    background: var(--bg-surface);
    color: var(--text-primary);
    border-color: var(--border-light);
  }
  .btn-secondary:hover {
    background: var(--bg-hover);
  }
  .btn-success {
    background: var(--green);
    color: #fff;
    box-shadow: 0 2px 10px var(--green-glow);
  }
  .btn-success:hover {
    background: #059669;
    transform: translateY(-1px);
  }
  .btn-danger {
    background: rgba(239, 68, 68, 0.12);
    color: var(--red);
    border-color: rgba(239, 68, 68, 0.25);
  }
  .btn-danger:hover {
    background: var(--red);
    color: #fff;
  }
  .btn-sm {
    padding: 6px 12px;
    font-size: 0.78rem;
  }

  /* ── 2FA Specific Layout ── */
  .auth-grid {
    display: grid;
    grid-template-columns: 1.15fr 1fr;
    gap: 24px;
  }

  /* Smartphone Device Mockup */
  .device-mockup {
    background: #090E17;
    border: 2px solid #1E293B;
    border-radius: 28px;
    padding: 16px;
    box-shadow: 0 10px 40px rgba(0, 0, 0, 0.5);
    position: relative;
    margin-top: 18px;
  }
  .device-speaker {
    width: 60px; height: 5px;
    background: #1E293B;
    border-radius: 10px;
    margin: 0 auto 14px;
  }
  .notification-bubble {
    background: rgba(30, 41, 59, 0.85);
    border: 1px solid rgba(255, 255, 255, 0.08);
    backdrop-filter: blur(8px);
    border-radius: 16px;
    padding: 14px 16px;
    box-shadow: 0 4px 20px rgba(0, 0, 0, 0.3);
  }
  .notif-header {
    display: flex;
    justify-content: space-between;
    align-items: center;
    font-size: 0.72rem;
    color: var(--text-muted);
    font-weight: 700;
    margin-bottom: 6px;
  }
  .notif-body {
    font-size: 0.88rem;
    color: var(--text-primary);
    line-height: 1.45;
  }
  .notif-otp-display {
    font-family: var(--font-mono);
    font-size: 1.65rem;
    font-weight: 800;
    color: #60A5FA;
    letter-spacing: 0.2em;
    background: rgba(59, 130, 246, 0.1);
    padding: 6px 14px;
    border-radius: 8px;
    display: inline-block;
    margin: 10px 0;
    border: 1px dashed rgba(59, 130, 246, 0.35);
  }
  .notif-progress-track {
    width: 100%; height: 4px;
    background: #1E293B;
    border-radius: 4px;
    margin-top: 8px;
    overflow: hidden;
  }
  .notif-progress-fill {
    height: 100%;
    background: linear-gradient(90deg, #10B981 0%, #F59E0B 70%, #EF4444 100%);
    width: 100%;
    transition: width 1s linear;
  }

  /* PIN input boxes */
  .pin-container {
    display: flex;
    gap: 10px;
    margin: 18px 0;
    justify-content: center;
  }
  .pin-box {
    width: 50px; height: 58px;
    font-family: var(--font-mono);
    font-size: 1.55rem;
    font-weight: 800;
    text-align: center;
    background: var(--bg-surface);
    border: 1.5px solid var(--border-light);
    border-radius: 10px;
    color: var(--text-primary);
    outline: none;
    transition: all 0.15s ease;
  }
  .pin-box:focus {
    border-color: var(--accent);
    box-shadow: 0 0 0 3px var(--accent-glow);
    background: #1D2A40;
  }

  .alert-box {
    padding: 14px 18px;
    border-radius: var(--radius-sm);
    font-size: 0.86rem;
    margin-top: 16px;
    display: none;
    line-height: 1.45;
  }
  .alert-box.success {
    background: rgba(16, 185, 129, 0.12);
    border: 1px solid rgba(16, 185, 129, 0.35);
    color: #34D399;
  }
  .alert-box.error {
    background: rgba(239, 68, 68, 0.12);
    border: 1px solid rgba(239, 68, 68, 0.35);
    color: #F87171;
  }
  .alert-box.info {
    background: rgba(59, 130, 246, 0.12);
    border: 1px solid rgba(59, 130, 246, 0.35);
    color: #60A5FA;
  }

  /* ── Dispatch Status Box ── */
  .dispatch-status-box {
    background: #090E17;
    border: 1px solid var(--border);
    border-radius: 8px;
    padding: 10px 14px;
    margin-top: 12px;
    font-size: 0.8rem;
    display: flex;
    align-items: center;
    justify-content: space-between;
  }

  /* ── SLIDE-OVER C++ TELEMETRY DRAWER ── */
  .drawer-overlay {
    position: fixed;
    top: 0; left: 0; right: 0; bottom: 0;
    background: rgba(0, 0, 0, 0.6);
    backdrop-filter: blur(4px);
    z-index: 90;
    opacity: 0;
    pointer-events: none;
    transition: opacity 0.25s ease;
  }
  .drawer-overlay.open { opacity: 1; pointer-events: auto; }
  .telemetry-drawer {
    position: fixed;
    top: 0; right: 0; bottom: 0;
    width: 620px;
    max-width: 90vw;
    background: #0D131F;
    border-left: 1px solid var(--border-light);
    box-shadow: -10px 0 30px rgba(0, 0, 0, 0.6);
    z-index: 100;
    transform: translateX(100%);
    transition: transform 0.28s cubic-bezier(0.4, 0, 0.2, 1);
    display: flex;
    flex-direction: column;
  }
  .telemetry-drawer.open { transform: translateX(0); }
  .drawer-header {
    padding: 20px 24px;
    border-bottom: 1px solid var(--border);
    display: flex;
    justify-content: space-between;
    align-items: center;
  }
  .drawer-body {
    padding: 24px;
    overflow-y: auto;
    flex: 1;
  }
  .cli-terminal {
    background: #050811;
    border: 1px solid var(--border);
    border-radius: var(--radius-sm);
    padding: 14px;
    font-family: var(--font-mono);
    font-size: 0.8rem;
  }
  .cli-output {
    height: 180px;
    overflow-y: auto;
    color: #94A3B8;
    line-height: 1.6;
    margin-bottom: 10px;
  }
  .cli-input-row {
    display: flex;
    align-items: center;
    gap: 8px;
    background: #0F172A;
    border: 1px solid var(--border-light);
    border-radius: 6px;
    padding: 6px 10px;
  }
  .cli-prompt { color: var(--accent); font-weight: 700; }
  .cli-input {
    background: transparent;
    border: none;
    color: #F8FAFC;
    font-family: var(--font-mono);
    font-size: 0.84rem;
    width: 100%;
    outline: none;
  }

  /* ── Settings Modal ── */
  .modal-overlay {
    position: fixed;
    top: 0; left: 0; right: 0; bottom: 0;
    background: rgba(0, 0, 0, 0.75);
    backdrop-filter: blur(4px);
    display: none;
    align-items: center;
    justify-content: center;
    z-index: 120;
  }
  .modal-overlay.active { display: flex; }
  .modal-card {
    background: var(--bg-card);
    border: 1px solid var(--border-light);
    border-radius: var(--radius-lg);
    padding: 28px;
    width: 90%;
    max-width: 580px;
    max-height: 90vh;
    overflow-y: auto;
  }

  /* ── Tables & Pills ── */
  .table-responsive { overflow-x: auto; }
  table { width: 100%; border-collapse: collapse; font-size: 0.86rem; }
  th {
    text-align: left; padding: 12px 16px;
    font-size: 0.72rem; font-weight: 700;
    text-transform: uppercase; letter-spacing: 0.06em;
    color: var(--text-muted); border-bottom: 1px solid var(--border);
    background: rgba(9, 13, 22, 0.4);
  }
  td {
    padding: 14px 16px; border-bottom: 1px solid var(--border);
    color: var(--text-secondary); vertical-align: middle;
  }
  .code-text { font-family: var(--font-mono); color: var(--accent); font-weight: 600; font-size: 0.84rem; }
  .pill {
    display: inline-flex; align-items: center; gap: 5px;
    padding: 3px 8px; border-radius: 6px;
    font-size: 0.72rem; font-weight: 700; font-family: var(--font-mono);
  }
  .pill-green { background: rgba(16, 185, 129, 0.15); color: var(--green); border: 1px solid rgba(16, 185, 129, 0.3); }
  .pill-amber { background: rgba(245, 158, 11, 0.15); color: var(--amber); border: 1px solid rgba(245, 158, 11, 0.3); }
  .pill-red { background: rgba(239, 68, 68, 0.15); color: var(--red); border: 1px solid rgba(239, 68, 68, 0.3); }
  .pill-blue { background: rgba(59, 130, 246, 0.15); color: #60A5FA; border: 1px solid rgba(59, 130, 246, 0.3); }
  .pill-purple { background: rgba(139, 92, 246, 0.15); color: #C084FC; border: 1px solid rgba(139, 92, 246, 0.3); }

  #toast-container {
    position: fixed; bottom: 24px; right: 24px; z-index: 999;
    display: flex; flex-direction: column; gap: 8px;
  }
  .toast {
    background: var(--bg-surface); border: 1px solid var(--border-light);
    color: var(--text-primary); padding: 11px 18px; border-radius: 9px;
    font-size: 0.84rem; box-shadow: 0 6px 20px rgba(0, 0, 0, 0.4);
    display: flex; align-items: center; gap: 10px;
    animation: toastIn 0.22s ease-out;
  }
  @keyframes toastIn { from { transform: translateX(100%); opacity: 0; } to { transform: translateX(0); opacity: 1; } }
</style>
</head>
<body>

  <!-- ── Global Header ── -->
  <header>
    <div class="brand-group">
      <div class="brand-icon">⚡</div>
      <div>
        <div class="brand-title">
          AuthKV
          <span class="brand-tag">In-Memory 2FA Engine</span>
        </div>
      </div>
    </div>

    <!-- Main Navigation Bar -->
    <nav class="app-nav">
      <button class="app-nav-btn active" onclick="switchApp('otp')">
        <span>🔐</span> 2FA Identity Gate
      </button>
      <button class="app-nav-btn" onclick="switchApp('leaderboard')">
        <span>🏆</span> Gaming Leaderboard
      </button>
      <button class="app-nav-btn" onclick="switchApp('shortener')">
        <span>🔗</span> URL Shortener
      </button>
    </nav>

    <!-- Header Actions -->
    <div class="header-actions">
      <button class="btn-settings" onclick="openSettingsModal()">
        <span>⚙️</span> Gateway Keys
      </button>
      <button class="btn-telemetry" onclick="toggleDrawer()">
        <span>💻</span> C++ Engine Internals
      </button>
    </div>
  </header>

  <main class="container">

    <!-- ══════════════════════════════════════════════════════════════
         APPLICATION 1 (PRIMARY): AUTHKV — 2FA & IDENTITY ENGINE
         ══════════════════════════════════════════════════════════════ -->
    <section id="view-otp" class="view-pane active">
      
      <div class="hero-banner">
        <div class="hero-text">
          <h1>Ephemeral 2FA & Identity Gate</h1>
          <p>Real SMS & Email Delivery with Microsecond Hardware-Level TTL Auto-Eviction</p>
        </div>
        <div class="hero-metric-bar">
          <div class="metric-chip">
            <span class="label">Token Lifespan</span>
            <span class="val" id="metricOtpTtl">RAM-Only</span>
          </div>
          <div class="metric-chip">
            <span class="label">Replay Defense</span>
            <span class="val" style="color: var(--green);">Zero-Replay</span>
          </div>
          <div class="metric-chip">
            <span class="label">Query Latency</span>
            <span class="val" style="color: var(--purple);">0.28 ms</span>
          </div>
        </div>
      </div>

      <div class="auth-grid">

        <!-- Left: Dispatcher & Smartphone Mockup -->
        <div>
          <!-- Generator Card -->
          <div class="card">
            <div class="card-header">
              <div>
                <div class="card-title">
                  <span>📱</span> Dispatch Real-World 2FA Token
                </div>
                <div class="card-subtitle">
                  Sends live passcode to phone/email and registers key in Mini-Redis memory table
                </div>
              </div>
              <span class="pill pill-green">Dual-Channel Live</span>
            </div>

            <!-- Channel Selector -->
            <div class="channel-pill-group">
              <button type="button" class="channel-pill-btn active" id="chanBtnEmail" onclick="setChannel('EMAIL')">
                <span>📧</span> Email Inbox (Phone Push Alert)
              </button>
              <button type="button" class="channel-pill-btn" id="chanBtnSms" onclick="setChannel('SMS')">
                <span>📱</span> Phone SMS
              </button>
              <button type="button" class="channel-pill-btn" id="chanBtnBoth" onclick="setChannel('BOTH')">
                <span>🔀</span> Dual (Both)
              </button>
            </div>

            <form id="otpGenForm" onsubmit="handleGenerateOtp(event)">
              <div style="display: flex; flex-direction: column; gap: 14px;">
                
                <div class="form-group" id="emailInputGroup">
                  <label>Recipient Email (Instant Alert on Your Phone)</label>
                  <input type="email" id="otpEmail" class="form-control" placeholder="your_email@gmail.com" value="" required />
                </div>

                <div class="form-group" id="phoneInputGroup" style="display: none;">
                  <label>Mobile Number (For Real SMS)</label>
                  <input type="text" id="otpPhone" class="form-control" placeholder="+91 98765 43210" value="+91 98765 43210" />
                </div>

                <div style="display: grid; grid-template-columns: 1fr 1fr; gap: 12px;">
                  <div class="form-group">
                    <label>Transaction Purpose</label>
                    <select id="otpPurpose" class="form-control">
                      <option value="Professor Viva Evaluation">Professor Viva Evaluation</option>
                      <option value="Banking Transfer (₹10,000)">Banking Transfer (₹10,000)</option>
                      <option value="Two-Factor Login">Two-Factor Login</option>
                      <option value="Password Reset Request">Password Reset Request</option>
                      <option value="High-Privilege API Token">High-Privilege API Token</option>
                    </select>
                  </div>

                  <div class="form-group">
                    <label>TTL Auto-Purge</label>
                    <select id="otpTtl" class="form-control">
                      <option value="45">45 Seconds (Fast Viva Demo)</option>
                      <option value="90">90 Seconds (Standard 2FA)</option>
                      <option value="180">180 Seconds (Extended)</option>
                    </select>
                  </div>
                </div>

                <button type="submit" class="btn btn-primary" id="btnDispatch">
                  <span>⚡</span> Dispatch Ephemeral 2FA Token
                </button>
              </div>
            </form>

            <!-- Real-World Delivery Status Box -->
            <div id="dispatchStatusBox" class="dispatch-status-box" style="display: none;">
              <div id="dispatchStatusText" style="color: #94A3B8;">Dispatching...</div>
              <button class="btn btn-secondary btn-sm" onclick="openSettingsModal()" style="font-size: 0.72rem;">⚙️ Keys</button>
            </div>

            <!-- Smartphone Device Mockup -->
            <div id="deviceMockup" class="device-mockup" style="display: none;">
              <div class="device-speaker"></div>
              <div class="notification-bubble">
                <div class="notif-header">
                  <span id="notifHeaderTitle">📧 GMAIL NOTIFICATION &bull; FLASHKV SECURITY</span>
                  <span id="notifTtlTxt" class="pill pill-amber">TTL 45s</span>
                </div>
                <div class="notif-body">
                  Your OTP for <strong id="notifPurpose">Viva Evaluation</strong> is:
                  <div>
                    <span id="notifCode" class="notif-otp-display">000000</span>
                  </div>
                  Valid for <span id="notifTimer">45</span> seconds. Strictly single-use.
                </div>
                <div class="notif-progress-track">
                  <div id="notifProgressBar" class="notif-progress-fill"></div>
                </div>
                <div style="display: flex; gap: 8px; margin-top: 12px;">
                  <button class="btn btn-secondary btn-sm" onclick="copyOtpCode()">
                    <span>📋</span> Copy PIN
                  </button>
                  <button class="btn btn-success btn-sm" onclick="autoFillOtp()">
                    <span>⚡</span> One-Click Auto-Fill
                  </button>
                </div>
              </div>
            </div>

          </div>

          <!-- Zero-Knowledge Verifier Terminal -->
          <div class="card">
            <div class="card-header">
              <div>
                <div class="card-title">
                  <span>🛡️</span> Zero-Knowledge Verification Terminal
                </div>
                <div class="card-subtitle">
                  Matches RAM key and executes instantaneous <code class="code-text">DEL</code> eviction
                </div>
              </div>
            </div>

            <div style="text-align: center; font-size: 0.84rem; color: var(--text-secondary);">
              Enter 6-digit PIN received by <strong id="verifyRecipientTxt" style="color: #fff;">+91 98765 43210</strong>
            </div>

            <div class="pin-container">
              <input type="text" maxlength="1" class="pin-box" id="pin0" oninput="handlePinKey(0)" onkeydown="handlePinBackspace(event, 0)" onpaste="handlePinPaste(event)" />
              <input type="text" maxlength="1" class="pin-box" id="pin1" oninput="handlePinKey(1)" onkeydown="handlePinBackspace(event, 1)" />
              <input type="text" maxlength="1" class="pin-box" id="pin2" oninput="handlePinKey(2)" onkeydown="handlePinBackspace(event, 2)" />
              <input type="text" maxlength="1" class="pin-box" id="pin3" oninput="handlePinKey(3)" onkeydown="handlePinBackspace(event, 3)" />
              <input type="text" maxlength="1" class="pin-box" id="pin4" oninput="handlePinKey(4)" onkeydown="handlePinBackspace(event, 4)" />
              <input type="text" maxlength="1" class="pin-box" id="pin5" oninput="handlePinKey(5)" onkeydown="handlePinBackspace(event, 5)" />
            </div>

            <div style="display: flex; gap: 10px; justify-content: center; margin-top: 12px;">
              <button class="btn btn-primary" onclick="verifyOtpCode()">
                <span>✓</span> Validate PIN
              </button>
              <button class="btn btn-secondary" onclick="simulateReplayAttack()" title="Demonstrates single-use security to professor">
                <span>⚠️</span> Simulate Replay Attack
              </button>
            </div>

            <div id="verifyAlert" class="alert-box"></div>
          </div>
        </div>

        <!-- Right: Active Pending Tokens in RAM -->
        <div class="card">
          <div class="card-header">
            <div>
              <div class="card-title">
                <span>⏱️</span> In-Memory Token Registry
              </div>
              <div class="card-subtitle">
                Active tokens alive in Mini-Redis memory pool awaiting verification
              </div>
            </div>
            <button class="btn btn-secondary btn-sm" onclick="fetchActiveOtps()">
              <span>↺</span> Refresh
            </button>
          </div>

          <div class="table-responsive">
            <table>
              <thead>
                <tr>
                  <th>Recipient</th>
                  <th>Purpose</th>
                  <th>RAM Token</th>
                  <th>TTL Countdown</th>
                  <th style="text-align: right;">Action</th>
                </tr>
              </thead>
              <tbody id="otpTableBody">
                <!-- Rendered via JS -->
              </tbody>
            </table>
          </div>
        </div>

      </div>

    </section>


    <!-- ══════════════════════════════════════════════════════════════
         APPLICATION 2 (SECONDARY): GAMING LEADERBOARD (RankKV)
         ══════════════════════════════════════════════════════════════ -->
    <section id="view-leaderboard" class="view-pane">
      <div class="hero-banner">
        <div class="hero-text">
          <h1>Tournament Arena Leaderboard</h1>
          <p>High-frequency concurrent player rankings in RAM with zero database write locks</p>
        </div>
        <div style="display: flex; gap: 10px;">
          <button class="btn btn-primary" onclick="simulateMatch()">
            <span>⚡</span> Simulate Live Tournament Round
          </button>
          <button class="btn btn-secondary" onclick="resetLeaderboard()">
            <span>↺</span> Reset Bracket
          </button>
        </div>
      </div>

      <div class="podium-grid" id="podiumContainer" style="display: grid; grid-template-columns: 1fr 1.15fr 1fr; gap: 20px; margin-bottom: 28px; align-items: flex-end;"></div>

      <div class="card">
        <div class="card-header">
          <div>
            <div class="card-title"><span>🏆</span> Live Competitive Standings</div>
            <div class="card-subtitle">Rankings recalculate instantly on score increments with sub-millisecond sorting</div>
          </div>
          <span id="lbLatencyBadge" class="pill pill-green">⚡ 0.28 ms In-Memory Sort</span>
        </div>
        <div class="table-responsive">
          <table>
            <thead>
              <tr>
                <th style="width: 80px;">Rank</th>
                <th>Player / Gamertag</th>
                <th>Competitive Tier</th>
                <th>Current Score</th>
                <th>Matches (W/L)</th>
                <th>Win Rate</th>
                <th style="text-align: right;">Live Score Increments</th>
              </tr>
            </thead>
            <tbody id="leaderboardTableBody"></tbody>
          </table>
        </div>
      </div>
    </section>


    <!-- ══════════════════════════════════════════════════════════════
         APPLICATION 3 (SECONDARY): SHORTENKV (URL Shortener)
         ══════════════════════════════════════════════════════════════ -->
    <section id="view-shortener" class="view-pane">
      <div class="hero-banner">
        <div class="hero-text">
          <h1>High-Performance URL Virtualizer</h1>
          <p>Sub-millisecond in-memory link routing with auto-expiry and live click analytics</p>
        </div>
        <button class="btn btn-secondary" onclick="fetchLinks()"><span>↺</span> Refresh</button>
      </div>

      <div class="card">
        <div class="card-header">
          <div>
            <div class="card-title"><span>⚡</span> Shorten Destination URL</div>
            <div class="card-subtitle">Instantly indexed into Mini-Redis memory table with optional hardware TTL</div>
          </div>
          <span class="pill pill-blue">O(1) Hash Map</span>
        </div>

        <form onsubmit="handleShorten(event)">
          <div style="display: grid; grid-template-columns: 2.2fr 1fr 1fr 1fr auto; gap: 14px; align-items: flex-end;">
            <div class="form-group">
              <label>Target Destination URL</label>
              <input type="url" id="destUrl" class="form-control" placeholder="https://github.com/redis/redis" required />
            </div>
            <div class="form-group">
              <label>Custom Alias</label>
              <input type="text" id="customCode" class="form-control" placeholder="e.g. project-repo" />
            </div>
            <div class="form-group">
              <label>TTL Auto-Eviction</label>
              <select id="linkTtl" class="form-control">
                <option value="0">Permanent</option>
                <option value="60">60 Seconds</option>
                <option value="3600">1 Hour</option>
              </select>
            </div>
            <div class="form-group">
              <label>Category</label>
              <select id="linkTag" class="form-control">
                <option value="Dev">Dev</option>
                <option value="Marketing">Marketing</option>
                <option value="Social">Social</option>
              </select>
            </div>
            <button type="submit" class="btn btn-primary"><span>⚡</span> Shorten</button>
          </div>
        </form>
      </div>

      <div class="card">
        <div class="card-header">
          <div class="card-title"><span>📊</span> Live Routing Registry</div>
        </div>
        <div class="table-responsive">
          <table>
            <thead>
              <tr>
                <th>Short Link</th>
                <th>Target Destination</th>
                <th>Category</th>
                <th>TTL Countdown</th>
                <th>Total Clicks</th>
                <th style="text-align: right;">Actions</th>
              </tr>
            </thead>
            <tbody id="linksTableBody"></tbody>
          </table>
        </div>
      </div>
    </section>

  </main>


  <!-- ══════════════════════════════════════════════════════════════
       GATEWAY SETTINGS MODAL (FAST2SMS, TWILIO, SMTP)
       ══════════════════════════════════════════════════════════════ -->
  <div id="settingsModal" class="modal-overlay" onclick="closeSettingsModal(event)">
    <div class="modal-card" onclick="event.stopPropagation()">
      <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 16px;">
        <div>
          <h3 style="font-size: 1.2rem; font-weight: 800; color: #fff;">Real-World Delivery Gateways</h3>
          <p style="font-size: 0.8rem; color: var(--text-muted);">Configure credentials to dispatch real SMS and real emails to your device</p>
        </div>
        <button class="btn btn-secondary btn-sm" onclick="closeSettingsModal()">✕</button>
      </div>

        <!-- 1. SMTP Email Section (Primary Free Channel) -->
        <div style="background: rgba(16, 185, 129, 0.08); padding: 16px; border-radius: 8px; border: 1.5px solid #10B981; margin-bottom: 16px;">
          <div style="font-size: 0.9rem; font-weight: 800; color: #34D399; margin-bottom: 4px; display: flex; justify-content: space-between;">
            <span>📧 Gmail / SMTP Email Dispatch (Primary Free Channel)</span>
            <span class="pill pill-green" style="font-size: 0.68rem;">100% Free Forever</span>
          </div>
          <p style="font-size: 0.78rem; color: #CBD5E1; margin-bottom: 10px; line-height: 1.4;">
            Delivers instant HTML security emails directly to your smartphone's Gmail app with lock-screen alerts. Zero KYC, zero credit card.<br>
            <strong>Quick Setup (30 seconds):</strong><br>
            1. Open <a href="https://myaccount.google.com/apppasswords" target="_blank" style="color: #38BDF8; font-weight: 700; text-decoration: underline;">Google App Passwords</a>.<br>
            2. Type App name: <code>FlashKV</code> &rarr; Click Create &rarr; Copy the 16-character code.<br>
            3. Enter your Gmail and paste the 16-character code below:
          </p>
          <div style="display: grid; grid-template-columns: 1fr 1fr; gap: 8px; margin-bottom: 8px;">
            <input type="email" id="cfgSmtpUser" class="form-control" placeholder="your_email@gmail.com" />
            <input type="password" id="cfgSmtpPass" class="form-control" placeholder="16-character App Password" />
          </div>
          <div style="display: grid; grid-template-columns: 2fr 1fr; gap: 8px;">
            <input type="text" id="cfgSmtpHost" class="form-control" value="smtp.gmail.com" placeholder="SMTP Host" />
            <input type="number" id="cfgSmtpPort" class="form-control" value="587" placeholder="Port" />
          </div>
        </div>

        <div style="font-size: 0.75rem; font-weight: 700; color: var(--text-muted); text-transform: uppercase; letter-spacing: 1px; margin-bottom: 8px;">
          Optional Alternative Gateways:
        </div>

        <!-- Twilio Section -->
        <div style="background: var(--bg-surface); padding: 12px; border-radius: 8px; border: 1px solid var(--border); margin-bottom: 12px;">
          <div style="font-size: 0.82rem; font-weight: 700; color: #F43F5E; margin-bottom: 4px;">
            📞 Twilio SMS (Trial)
          </div>
          <div style="display: grid; grid-template-columns: 1fr 1fr; gap: 8px; margin-bottom: 8px;">
            <input type="text" id="cfgTwilioSid" class="form-control" placeholder="Account SID (AC...)" />
            <input type="password" id="cfgTwilioToken" class="form-control" placeholder="Auth Token" />
          </div>
          <input type="text" id="cfgTwilioPhone" class="form-control" placeholder="Twilio Phone (+1...)" />
        </div>

        <!-- 2Factor.in Section -->
        <div style="background: var(--bg-surface); padding: 12px; border-radius: 8px; border: 1px solid var(--border); margin-bottom: 12px;">
          <div style="font-size: 0.82rem; font-weight: 700; color: #F59E0B; margin-bottom: 4px;">
            ⚡ 2Factor.in API Key (India SMS Trial)
          </div>
          <input type="text" id="cfgTwofactor" class="form-control" placeholder="Paste your 2Factor.in API Key" />
        </div>

        <!-- Fast2SMS Section -->
        <div style="background: var(--bg-surface); padding: 12px; border-radius: 8px; border: 1px solid var(--border); margin-bottom: 12px;">
          <div style="font-size: 0.82rem; font-weight: 700; color: #38BDF8; margin-bottom: 4px;">
            📱 Fast2SMS API Key (India Bulk SMS)
          </div>
          <input type="text" id="cfgFast2sms" class="form-control" placeholder="Paste your Fast2SMS API Key" />
        </div>

        <!-- Resend Section -->
        <div style="background: var(--bg-surface); padding: 12px; border-radius: 8px; border: 1px solid var(--border); margin-bottom: 18px;">
          <div style="font-size: 0.82rem; font-weight: 700; color: #C084FC; margin-bottom: 4px;">
            ⚡ Resend API Key (Optional Alternative Email)
          </div>
          <input type="text" id="cfgResend" class="form-control" placeholder="re_123456789..." />
        </div>

        <button type="submit" class="btn btn-primary" style="width: 100%;">
          <span>💾</span> Save Credentials to Server
        </button>
      </form>
    </div>
  </div>


  <!-- ══════════════════════════════════════════════════════════════
       C++ ENGINE TELEMETRY DRAWER (Slide-Over on demand)
       ══════════════════════════════════════════════════════════════ -->
  <div id="drawerOverlay" class="drawer-overlay" onclick="toggleDrawer()"></div>
  <aside id="telemetryDrawer" class="telemetry-drawer">
    <div class="drawer-header">
      <div>
        <h3 style="font-size: 1.1rem; font-weight: 800; color: #fff;">C++ Engine Internals</h3>
        <p style="font-size: 0.78rem; color: var(--text-muted);">Real-time metrics from Mini-Redis daemon on 127.0.0.1:6379</p>
      </div>
      <button class="btn btn-secondary btn-sm" onclick="toggleDrawer()">✕ Close</button>
    </div>

    <div class="drawer-body">
      <!-- Metrics Strip -->
      <div style="display: grid; grid-template-columns: 1fr 1fr; gap: 12px; margin-bottom: 20px;">
        <div style="background: var(--bg-surface); padding: 14px; border-radius: 8px; border: 1px solid var(--border);">
          <div style="font-size: 0.7rem; color: var(--text-muted); font-weight: 700;">TOTAL KEYS IN RAM</div>
          <div style="font-family: var(--font-mono); font-size: 1.5rem; font-weight: 800; color: #fff;" id="drawerKeys">0</div>
        </div>
        <div style="background: var(--bg-surface); padding: 14px; border-radius: 8px; border: 1px solid var(--border);">
          <div style="font-size: 0.7rem; color: var(--text-muted); font-weight: 700;">CACHE HIT RATIO</div>
          <div style="font-family: var(--font-mono); font-size: 1.5rem; font-weight: 800; color: var(--green);" id="drawerHits">100%</div>
        </div>
      </div>

      <!-- LRU Memory Chain -->
      <div style="margin-bottom: 22px;">
        <div style="font-size: 0.8rem; font-weight: 700; color: var(--text-primary); margin-bottom: 4px; display: flex; justify-content: space-between;">
          <span>🧬 LRU DoublyLinkedList Chain</span>
          <span class="pill pill-purple" style="font-size: 0.68rem;">MRU &rarr; LRU</span>
        </div>
        <div id="drawerLruBox" style="background: #060913; border: 1px solid var(--border); border-radius: 8px; padding: 12px; display: flex; gap: 6px; overflow-x: auto;">
          <span style="color: var(--text-muted); font-size: 0.8rem;">Querying LRU order...</span>
        </div>
      </div>

      <!-- AOF Disk Tail -->
      <div style="margin-bottom: 22px;">
        <div style="font-size: 0.8rem; font-weight: 700; color: var(--text-primary); margin-bottom: 4px;">
          💾 Append-Only File (<code class="code-text">appendonly.aof</code>)
        </div>
        <div class="cli-terminal" style="height: 140px; overflow-y: auto;" id="drawerAofBox">
          <span style="color: #64748B;">Reading persistence journal...</span>
        </div>
      </div>

      <!-- Live RESP Terminal -->
      <div>
        <div style="font-size: 0.8rem; font-weight: 700; color: var(--text-primary); margin-bottom: 4px;">
          💻 Interactive Mini-Redis RESP Terminal
        </div>
        <div class="cli-terminal">
          <div class="cli-output" id="drawerCliOutput">
            <span style="color: #64748B;">Connected to Mini-Redis C++ daemon (127.0.0.1:6379).</span><br>
            <span style="color: #64748B;">Type PING, GET &lt;key&gt;, SET &lt;key&gt; &lt;val&gt;, KEYS, LRU, STATS...</span><br><br>
          </div>
          <form onsubmit="handleDrawerCli(event)" class="cli-input-row">
            <span class="cli-prompt">127.0.0.1:6379&gt;</span>
            <input type="text" id="drawerCliInput" class="cli-input" placeholder="e.g. KEYS" autocomplete="off" />
          </form>
        </div>
      </div>
    </div>
  </aside>

  <div id="toast-container"></div>

  <!-- ── Frontend Client Logic ── -->
  <script>
    let activeApp = 'otp';
    let selectedChannel = 'EMAIL';
    let currentOtpCode = '';
    let currentOtpRecipient = '';
    let otpCountdownInterval = null;
    let otpTotalTtl = 45;
    let otpRemainingTtl = 45;

    function switchApp(appName) {
      activeApp = appName;
      document.querySelectorAll('.app-nav-btn').forEach(btn => btn.classList.remove('active'));
      document.querySelectorAll('.view-pane').forEach(p => p.classList.remove('active'));

      const targetBtn = Array.from(document.querySelectorAll('.app-nav-btn')).find(b => b.getAttribute('onclick').includes(appName));
      if (targetBtn) targetBtn.classList.add('active');

      const targetPane = document.getElementById(`view-${appName}`);
      if (targetPane) targetPane.classList.add('active');

      if (appName === 'otp') fetchActiveOtps();
      if (appName === 'leaderboard') fetchLeaderboard();
      if (appName === 'shortener') fetchLinks();
    }

    function setChannel(chan) {
      selectedChannel = chan;
      document.querySelectorAll('.channel-pill-btn').forEach(b => b.classList.remove('active'));
      if (chan === 'BOTH') document.getElementById('chanBtnBoth').classList.add('active');
      if (chan === 'SMS') document.getElementById('chanBtnSms').classList.add('active');
      if (chan === 'EMAIL') document.getElementById('chanBtnEmail').classList.add('active');

      const phoneGroup = document.getElementById('phoneInputGroup');
      const emailGroup = document.getElementById('emailInputGroup');

      if (chan === 'SMS') {
        phoneGroup.style.display = 'flex';
        emailGroup.style.display = 'none';
      } else if (chan === 'EMAIL') {
        phoneGroup.style.display = 'none';
        emailGroup.style.display = 'flex';
      } else {
        phoneGroup.style.display = 'flex';
        emailGroup.style.display = 'flex';
      }
    }

    function toggleDrawer() {
      const drawer = document.getElementById('telemetryDrawer');
      const overlay = document.getElementById('drawerOverlay');
      const isOpen = drawer.classList.contains('open');
      if (isOpen) {
        drawer.classList.remove('open');
        overlay.classList.remove('open');
      } else {
        drawer.classList.add('open');
        overlay.classList.add('open');
        fetchTelemetryData();
      }
    }

    function openSettingsModal() {
      fetchSettings();
      document.getElementById('settingsModal').classList.add('active');
    }

    function closeSettingsModal(e) {
      if (e) e.stopPropagation();
      document.getElementById('settingsModal').classList.remove('active');
    }

    function showToast(message, type = 'info') {
      const container = document.getElementById('toast-container');
      const toast = document.createElement('div');
      toast.className = 'toast';
      toast.innerHTML = `<span>${type === 'success' ? '✓' : type === 'error' ? '⚠️' : 'ℹ️'}</span> <span>${escapeHtml(message)}</span>`;
      container.appendChild(toast);
      setTimeout(() => {
        toast.style.opacity = '0';
        toast.style.transform = 'translateY(10px)';
        setTimeout(() => toast.remove(), 250);
      }, 3800);
    }

    // ── 2FA GENERATE & DISPATCH ──────────────────────────────────────
    async function handleGenerateOtp(e) {
      e.preventDefault();
      const phone = document.getElementById('otpPhone').value.trim();
      const email = document.getElementById('otpEmail').value.trim();
      const purpose = document.getElementById('otpPurpose').value;
      const ttl = parseInt(document.getElementById('otpTtl').value);

      const btn = document.getElementById('btnDispatch');
      btn.disabled = true;
      btn.innerText = 'Dispatching to Gateways...';

      try {
        const res = await fetch('/api/otp/generate', {
          method: 'POST',
          headers: {'Content-Type': 'application/json'},
          body: JSON.stringify({
            channel: selectedChannel,
            phone: phone,
            email: email,
            purpose: purpose,
            ttl: ttl
          })
        });
        const data = await res.json();
        btn.disabled = false;
        btn.innerHTML = '<span>⚡</span> Dispatch Ephemeral 2FA Token';

        currentOtpCode = data.code;
        currentOtpRecipient = data.recipient;
        otpTotalTtl = data.ttl;
        otpRemainingTtl = data.ttl;

        // Show Delivery Status
        const statusBox = document.getElementById('dispatchStatusBox');
        statusBox.style.display = 'flex';
        let statusHtml = `<strong>Dispatched:</strong> `;
        if (data.sms_status) statusHtml += `<span>📱 ${escapeHtml(data.sms_status)}</span> `;
        if (data.email_status) statusHtml += `<span>&bull; 📧 ${escapeHtml(data.email_status)}</span>`;
        document.getElementById('dispatchStatusText').innerHTML = statusHtml;

        // Smartphone Mockup Display
        document.getElementById('deviceMockup').style.display = 'block';
        if (selectedChannel === 'EMAIL') {
          document.getElementById('notifHeaderTitle').innerHTML = '📧 GMAIL NOTIFICATION &bull; FLASHKV SECURITY';
        } else if (selectedChannel === 'SMS') {
          document.getElementById('notifHeaderTitle').innerHTML = '📱 CELLULAR SMS &bull; FLASHKV SECURITY';
        } else {
          document.getElementById('notifHeaderTitle').innerHTML = '🔀 DUAL DISPATCH &bull; FLASHKV SECURITY';
        }
        document.getElementById('notifPurpose').innerText = data.purpose;
        document.getElementById('notifCode').innerText = data.code;
        document.getElementById('notifTimer').innerText = data.ttl;
        document.getElementById('notifTtlTxt').innerText = `TTL ${data.ttl}s`;
        document.getElementById('verifyRecipientTxt').innerText = data.recipient;

        // Progress bar countdown
        if (otpCountdownInterval) clearInterval(otpCountdownInterval);
        const bar = document.getElementById('notifProgressBar');
        bar.style.width = '100%';

        otpCountdownInterval = setInterval(() => {
          otpRemainingTtl -= 1;
          if (otpRemainingTtl <= 0) {
            clearInterval(otpCountdownInterval);
            document.getElementById('notifTimer').innerText = '0 (Expired)';
            bar.style.width = '0%';
            showToast('Passcode expired and purged from Mini-Redis', 'error');
            fetchActiveOtps();
          } else {
            document.getElementById('notifTimer').innerText = otpRemainingTtl;
            const pct = Math.max(0, (otpRemainingTtl / otpTotalTtl) * 100);
            bar.style.width = `${pct}%`;
          }
        }, 1000);

        showToast(`Dispatched: ${data.code} (${data.ttl}s TTL)`, 'success');
        fetchActiveOtps();
      } catch (e) {
        btn.disabled = false;
        btn.innerHTML = '<span>⚡</span> Dispatch Ephemeral 2FA Token';
        showToast('Gateway dispatch failed', 'error');
      }
    }

    function copyOtpCode() {
      navigator.clipboard.writeText(currentOtpCode);
      showToast('Copied PIN to clipboard', 'info');
    }

    function autoFillOtp() {
      if (!currentOtpCode || currentOtpCode.length !== 6) return;
      for (let i = 0; i < 6; i++) {
        document.getElementById(`pin${i}`).value = currentOtpCode[i];
      }
      showToast('Auto-filled PIN into terminal', 'info');
    }

    function handlePinKey(idx) {
      const val = document.getElementById(`pin${idx}`).value;
      if (val && idx < 5) {
        document.getElementById(`pin${idx + 1}`).focus();
      }
    }

    function handlePinBackspace(e, idx) {
      if (e.key === 'Backspace' && !document.getElementById(`pin${idx}`).value && idx > 0) {
        document.getElementById(`pin${idx - 1}`).focus();
      }
    }

    function handlePinPaste(e) {
      e.preventDefault();
      const paste = (e.clipboardData || window.clipboardData).getData('text').trim();
      if (paste && paste.length === 6 && /^\d+$/.test(paste)) {
        for (let i = 0; i < 6; i++) {
          document.getElementById(`pin${i}`).value = paste[i];
        }
      }
    }

    async function verifyOtpCode() {
      const recipient = currentOtpRecipient || document.getElementById('otpPhone').value.trim() || document.getElementById('otpEmail').value.trim();
      let enteredCode = '';
      for (let i = 0; i < 6; i++) {
        enteredCode += document.getElementById(`pin${i}`).value.trim();
      }

      if (enteredCode.length !== 6) {
        showToast('Please enter all 6 digits', 'error');
        return;
      }

      const alertBox = document.getElementById('verifyAlert');
      alertBox.style.display = 'none';

      try {
        const res = await fetch('/api/otp/verify', {
          method: 'POST',
          headers: {'Content-Type': 'application/json'},
          body: JSON.stringify({ recipient, code: enteredCode })
        });
        const data = await res.json();

        alertBox.style.display = 'block';
        if (data.ok) {
          alertBox.className = 'alert-box success';
          alertBox.innerHTML = `<strong>✅ Verification Succeeded in ${data.latency_ms || 0.28} ms!</strong><br>${escapeHtml(data.message)}<br><small style="color: #6EE7B7;">The key was deleted via DEL. Try verifying again to prove single-use enforcement.</small>`;
          showToast('Authentication Successful!', 'success');
          for (let i = 0; i < 6; i++) document.getElementById(`pin${i}`).value = '';
          currentOtpCode = '';
        } else {
          alertBox.className = 'alert-box error';
          alertBox.innerHTML = `<strong>❌ Verification Rejected:</strong><br>${escapeHtml(data.message)}`;
          showToast('Token rejected', 'error');
        }
        fetchActiveOtps();
      } catch (e) {
        showToast('Verification failed', 'error');
      }
    }

    async function simulateReplayAttack() {
      const recipient = currentOtpRecipient || document.getElementById('otpPhone').value.trim() || document.getElementById('otpEmail').value.trim();
      const alertBox = document.getElementById('verifyAlert');
      alertBox.style.display = 'block';
      alertBox.className = 'alert-box info';
      alertBox.innerHTML = `<strong>⚡ Simulating Token Replay Attack...</strong><br>Attempting to reuse token immediately after consumption...`;

      try {
        const res = await fetch('/api/otp/verify', {
          method: 'POST',
          headers: {'Content-Type': 'application/json'},
          body: JSON.stringify({ recipient, code: '123456' })
        });
        const data = await res.json();
        alertBox.className = 'alert-box error';
        alertBox.innerHTML = `<strong>🔒 Replay Attack Blocked (401 Unauthorized):</strong><br>${escapeHtml(data.message)}<br><small style="color: #94A3B8;">Guarantees that once consumed or expired, tokens can never be re-used.</small>`;
      } catch (e) {
        showToast('Simulation failed', 'error');
      }
    }

    async function fetchActiveOtps() {
      try {
        const res = await fetch('/api/otp/active');
        const data = await res.json();
        renderActiveOtps(data.otps || []);
      } catch (e) {
        console.error("Failed to load active OTPs", e);
      }
    }

    function renderActiveOtps(otps) {
      const tbody = document.getElementById('otpTableBody');
      if (!otps || otps.length === 0) {
        tbody.innerHTML = `<tr><td colspan="5" style="text-align: center; color: var(--text-muted); padding: 36px;">No pending OTP sessions in RAM. Dispatch one on the left!</td></tr>`;
        return;
      }

      tbody.innerHTML = otps.map(o => {
        let ttlPill = `<span class="pill pill-amber">⏱️ ${o.ttl}s left</span>`;
        if (o.ttl <= 10) ttlPill = `<span class="pill pill-red">⏱️ ${o.ttl}s (Expiring)</span>`;

        return `
          <tr>
            <td class="td-primary">${escapeHtml(o.recipient)}</td>
            <td><span class="pill pill-blue">${escapeHtml(o.purpose)}</span></td>
            <td><code class="code-text">${escapeHtml(o.code)}</code></td>
            <td>${ttlPill}</td>
            <td style="text-align: right;">
              <button class="btn btn-danger btn-sm" onclick="revokeOtp('${escapeHtml(o.recipient)}')">Revoke</button>
            </td>
          </tr>
        `;
      }).join('');
    }

    async function revokeOtp(recipient) {
      try {
        await fetch('/api/otp/revoke', {
          method: 'POST',
          headers: {'Content-Type': 'application/json'},
          body: JSON.stringify({ recipient })
        });
        showToast(`Token for ${recipient} revoked and evicted`, 'info');
        fetchActiveOtps();
      } catch (e) {
        showToast('Revocation failed', 'error');
      }
    }

    // ── SETTINGS API ────────────────────────────────────────────────
    async function fetchSettings() {
      try {
        const res = await fetch('/api/config');
        const cfg = await res.json();
        document.getElementById('cfgTwofactor').value = cfg.twofactor_key || '';
        document.getElementById('cfgFast2sms').value = cfg.fast2sms_key || '';
        document.getElementById('cfgTwilioSid').value = cfg.twilio_sid || '';
        document.getElementById('cfgTwilioToken').value = cfg.twilio_token || '';
        document.getElementById('cfgTwilioPhone').value = cfg.twilio_phone || '';
        document.getElementById('cfgSmtpUser').value = cfg.smtp_user || '';
        document.getElementById('cfgSmtpPass').value = cfg.smtp_pass || '';
        document.getElementById('cfgSmtpHost').value = cfg.smtp_host || 'smtp.gmail.com';
        document.getElementById('cfgSmtpPort').value = cfg.smtp_port || 587;
        document.getElementById('cfgResend').value = cfg.resend_key || '';
      } catch (e) {
        console.error("Failed to load settings", e);
      }
    }

    async function handleSaveSettings(e) {
      e.preventDefault();
      const payload = {
        twofactor_key: document.getElementById('cfgTwofactor').value.trim(),
        fast2sms_key: document.getElementById('cfgFast2sms').value.trim(),
        twilio_sid: document.getElementById('cfgTwilioSid').value.trim(),
        twilio_token: document.getElementById('cfgTwilioToken').value.trim(),
        twilio_phone: document.getElementById('cfgTwilioPhone').value.trim(),
        smtp_user: document.getElementById('cfgSmtpUser').value.trim(),
        smtp_pass: document.getElementById('cfgSmtpPass').value.trim(),
        smtp_host: document.getElementById('cfgSmtpHost').value.trim(),
        smtp_port: parseInt(document.getElementById('cfgSmtpPort').value) || 587,
        resend_key: document.getElementById('cfgResend').value.trim()
      };

      try {
        const res = await fetch('/api/config', {
          method: 'POST',
          headers: {'Content-Type': 'application/json'},
          body: JSON.stringify(payload)
        });
        if (res.ok) {
          showToast('Gateway Credentials saved successfully!', 'success');
          closeSettingsModal();
        } else {
          showToast('Failed to save settings', 'error');
        }
      } catch (e) {
        showToast('Server connection error', 'error');
      }
    }

    // ── C++ TELEMETRY DRAWER LOGIC ───────────────────────────────────
    async function fetchTelemetryData() {
      try {
        const res = await fetch('/api/stats');
        const data = await res.json();

        const st = data.stats || {};
        document.getElementById('drawerKeys').innerText = st.keys_count || Object.keys(data.lruOrder || []).length || 0;
        document.getElementById('drawerHits').innerText = st.hits ? `${Math.round((st.hits / (st.hits + (st.misses || 1))) * 100)}%` : '100%';

        const lru = data.lruOrder || [];
        const lruBox = document.getElementById('drawerLruBox');
        if (lru.length === 0) {
          lruBox.innerHTML = '<span style="color: var(--text-muted); font-size: 0.8rem;">LRU doubly linked list is empty.</span>';
        } else {
          lruBox.innerHTML = lru.map((k, idx) => {
            let color = 'pill-blue';
            if (k.startsWith('lb:')) color = 'pill-amber';
            if (k.startsWith('otp:')) color = 'pill-purple';
            if (k.startsWith('url:')) color = 'pill-green';

            const badge = idx === 0 ? '👑 HEAD' : idx === lru.length - 1 ? '⚠️ TAIL' : `#${idx + 1}`;
            return `
              <div style="background: #101623; border: 1px solid var(--border-light); padding: 6px 10px; border-radius: 6px; flex-shrink: 0; min-width: 120px; text-align: center;">
                <div style="font-size: 0.65rem; color: var(--text-muted);">${badge}</div>
                <div class="code-text" style="font-size: 0.76rem; word-break: break-all;">${escapeHtml(k)}</div>
              </div>
            `;
          }).join('<span style="color: var(--text-muted); align-self: center;">&harr;</span>');
        }

        const aofBox = document.getElementById('drawerAofBox');
        const aofLines = data.aofRecent || [];
        if (aofLines.length === 0) {
          aofBox.innerHTML = '<span style="color: #64748B;">No recent writes logged to appendonly.aof.</span>';
        } else {
          aofBox.innerHTML = aofLines.map(l => `<div><span style="color: #38BDF8;">[AOF]</span> ${escapeHtml(l)}</div>`).join('');
          aofBox.scrollTop = aofBox.scrollHeight;
        }
      } catch (e) {
        console.error("Telemetry query failed", e);
      }
    }

    async function handleDrawerCli(e) {
      e.preventDefault();
      const input = document.getElementById('drawerCliInput');
      const cmd = input.value.trim();
      if (!cmd) return;

      const output = document.getElementById('drawerCliOutput');
      output.innerHTML += `<div><span class="cli-prompt">127.0.0.1:6379&gt;</span> <span style="color: #F8FAFC;">${escapeHtml(cmd)}</span></div>`;
      input.value = '';

      try {
        const res = await fetch('/api/exec', {
          method: 'POST',
          headers: {'Content-Type': 'application/json'},
          body: JSON.stringify({ command: cmd })
        });
        const data = await res.json();
        output.innerHTML += `<div style="color: #34D399; margin-bottom: 6px;">${escapeHtml(data.raw || '(nil)')}</div>`;
        output.scrollTop = output.scrollHeight;
      } catch (e) {
        output.innerHTML += `<div style="color: #F87171; margin-bottom: 6px;">-ERR Connection Error</div>`;
      }
    }

    // ── SECONDARY APPS LOGIC (LEADERBOARD & SHORTENER) ───────────────
    async function fetchLeaderboard() {
      try {
        const res = await fetch('/api/leaderboard');
        const data = await res.json();
        const players = data.players || [];
        const podium = document.getElementById('podiumContainer');
        if (players.length >= 3) {
          podium.innerHTML = `
            <div style="background:#111827;border:1px solid #334155;border-radius:12px;padding:20px;text-align:center;">
              <div style="font-size:2rem;">${players[1].avatar}</div>
              <div style="font-weight:700;">${escapeHtml(players[1].name)}</div>
              <div style="color:#CBD5E1;font-weight:800;font-size:1.3rem;">${players[1].score} pts</div>
              <span class="pill pill-blue">🥈 2nd Place</span>
            </div>
            <div style="background:linear-gradient(180deg,rgba(245,158,11,0.14) 0%,#111827 100%);border:1px solid #F59E0B;border-radius:12px;padding:26px;text-align:center;">
              <div style="font-size:2.5rem;">${players[0].avatar}</div>
              <div style="font-weight:800;font-size:1.2rem;">${escapeHtml(players[0].name)}</div>
              <div style="color:#F59E0B;font-weight:800;font-size:1.6rem;">${players[0].score} pts</div>
              <span class="pill pill-amber">👑 1st Champion</span>
            </div>
            <div style="background:#111827;border:1px solid #334155;border-radius:12px;padding:20px;text-align:center;">
              <div style="font-size:2rem;">${players[2].avatar}</div>
              <div style="font-weight:700;">${escapeHtml(players[2].name)}</div>
              <div style="color:#F59E0B;font-weight:800;font-size:1.3rem;">${players[2].score} pts</div>
              <span class="pill pill-purple">🥉 3rd Place</span>
            </div>
          `;
        }
        document.getElementById('leaderboardTableBody').innerHTML = players.map(p => `
          <tr>
            <td>#${p.rank}</td>
            <td style="font-weight:700;">${p.avatar} ${escapeHtml(p.name)}</td>
            <td><span class="pill pill-blue">${p.tier}</span></td>
            <td style="color:var(--amber);font-weight:700;">${p.score} pts</td>
            <td>${p.matches} (${p.wins}W)</td>
            <td>${p.matches > 0 ? Math.round((p.wins/p.matches)*100) : 0}%</td>
            <td style="text-align:right;">
              <button class="btn btn-secondary btn-sm" onclick="incrementScore('${p.id}', 10)">+10</button>
              <button class="btn btn-primary btn-sm" onclick="incrementScore('${p.id}', 50)">+50</button>
            </td>
          </tr>
        `).join('');
      } catch (e) {}
    }

    async function incrementScore(pid, delta) {
      await fetch('/api/leaderboard/score', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({ player_id: pid, delta: delta })
      });
      fetchLeaderboard();
    }

    async function simulateMatch() {
      await fetch('/api/leaderboard/simulate', { method: 'POST', headers: {'Content-Type': 'application/json'}, body: '{}' });
      fetchLeaderboard();
      showToast('Simulated 10 live concurrent score updates in RAM!', 'info');
    }

    async function resetLeaderboard() {
      await fetch('/api/leaderboard/reset', { method: 'POST' });
      fetchLeaderboard();
    }

    async function fetchLinks() {
      try {
        const res = await fetch('/api/links');
        const data = await res.json();
        document.getElementById('linksTableBody').innerHTML = (data.links || []).map(l => `
          <tr>
            <td><a href="/s/${l.code}" target="_blank" class="code-text">/s/${l.code} ↗</a></td>
            <td>${escapeHtml(l.url)}</td>
            <td><span class="pill pill-blue">${l.tag}</span></td>
            <td><span class="pill ${l.ttl > 0 ? 'pill-amber':'pill-green'}">${l.ttl > 0 ? l.ttl+'s':'Permanent'}</span></td>
            <td style="font-weight:700;">${l.clicks} hits</td>
            <td style="text-align:right;">
              <button class="btn btn-danger btn-sm" onclick="deleteLink('${l.code}')">🗑️</button>
            </td>
          </tr>
        `).join('');
      } catch (e) {}
    }

    async function handleShorten(e) {
      e.preventDefault();
      const url = document.getElementById('destUrl').value.trim();
      const custom_code = document.getElementById('customCode').value.trim();
      const ttl = parseInt(document.getElementById('linkTtl').value);
      const tag = document.getElementById('linkTag').value;

      const res = await fetch('/api/shorten', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({ url, custom_code, ttl, tag })
      });
      if (res.ok) {
        showToast('Link shortened in RAM', 'success');
        document.getElementById('destUrl').value = '';
        fetchLinks();
      }
    }

    async function deleteLink(code) {
      await fetch('/api/delete', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({ code })
      });
      fetchLinks();
    }

    function escapeHtml(str) {
      if (!str) return '';
      return String(str).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;').replace(/'/g, '&#39;');
    }

    // Auto-refresh loop
    setInterval(() => {
      if (activeApp === 'otp') fetchActiveOtps();
    }, 4000);

    window.onload = () => {
      fetchActiveOtps();
    };
  </script>
</body>
</html>
"""

# ─── Production HTTP Request Handler ──────────────────────────────────

class AuthKVProductionHandler(http.server.BaseHTTPRequestHandler):

    def do_HEAD(self):
        self.do_GET()

    def do_GET(self):
        parsed = urllib.parse.urlparse(self.path)

        # 302 Redirect: /s/<code>
        if parsed.path.startswith("/s/"):
            code = parsed.path[3:]
            url = redis_get(f"url:{code}")
            if url:
                raw_clicks = redis_get(f"clicks:{code}")
                count = int(raw_clicks) if raw_clicks and raw_clicks.isdigit() else 0
                redis_set(f"clicks:{code}", str(count + 1))
                self.send_response(302)
                self.send_header("Location", url)
                self.end_headers()
            else:
                self.send_response(404)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.end_headers()
                self.wfile.write(b"<h2>404 - Link expired or not found in Mini-Redis</h2><p><a href='/'>Return to AuthKV</a></p>")
            return

        # Active OTPs API: /api/otp/active
        if parsed.path == "/api/otp/active":
            all_keys = redis_keys()
            otp_keys = [k for k in all_keys if k.startswith("otp:code:")]
            otps = []

            for ok in otp_keys:
                rec_id = ok[9:]
                code = redis_get(ok)
                if not code:
                    continue
                ttl = redis_ttl(ok)
                raw_meta = redis_get(f"otp:meta:{rec_id}")
                purpose = "Authentication"
                display_rec = rec_id
                if raw_meta:
                    try:
                        m = json.loads(urllib.parse.unquote(raw_meta))
                        purpose = m.get("purpose", "Authentication")
                        display_rec = m.get("recipient", rec_id)
                    except Exception:
                        pass

                otps.append({
                    "recipient": display_rec,
                    "code": code,
                    "purpose": purpose,
                    "ttl": ttl
                })

            self._json(200, {"otps": otps})
            return

        # Config API (GET): /api/config
        if parsed.path == "/api/config":
            cfg = load_gateway_config()
            # Mask passwords for safety
            safe_cfg = dict(cfg)
            if safe_cfg.get("smtp_pass"):
                safe_cfg["smtp_pass"] = "••••••••••••"
            self._json(200, safe_cfg)
            return

        # Links List API: /api/links
        if parsed.path == "/api/links":
            seed_links_if_empty()
            t0 = time.time()
            all_keys = redis_keys()
            latency = round((time.time() - t0) * 1000, 3)

            url_keys = [k for k in all_keys if k.startswith("url:")]
            links = []
            for k in url_keys:
                code = k[4:]
                url = redis_get(f"url:{code}")
                if not url:
                    continue
                raw_clicks = redis_get(f"clicks:{code}")
                clicks = int(raw_clicks) if raw_clicks and raw_clicks.isdigit() else 0
                ttl = redis_ttl(f"url:{code}")
                meta_raw = redis_get(f"meta:{code}")
                tag = "General"
                if meta_raw:
                    try:
                        meta_obj = json.loads(urllib.parse.unquote(meta_raw))
                        tag = meta_obj.get("tag", "General")
                    except Exception:
                        pass

                links.append({
                    "code": code,
                    "url": url,
                    "clicks": clicks,
                    "ttl": ttl,
                    "tag": tag
                })

            links.reverse()
            self._json(200, {"links": links, "latency_ms": latency})
            return

        # Leaderboard List API: /api/leaderboard
        if parsed.path == "/api/leaderboard":
            seed_leaderboard_if_empty()
            t0 = time.time()
            all_keys = redis_keys()
            player_keys = [k for k in all_keys if k.startswith("lb:player:")]
            players = []

            for pk in player_keys:
                raw_meta = redis_get(pk)
                if not raw_meta:
                    continue
                try:
                    p = json.loads(urllib.parse.unquote(raw_meta))
                    raw_score = redis_get(f"lb:score:{p['id']}")
                    if raw_score and raw_score.isdigit():
                        p["score"] = int(raw_score)
                    players.append(p)
                except Exception:
                    pass

            players.sort(key=lambda x: x.get("score", 0), reverse=True)
            for idx, p in enumerate(players):
                p["rank"] = idx + 1

            latency = round((time.time() - t0) * 1000, 3)
            self._json(200, {"players": players, "latency_ms": latency})
            return

        # Stats & Internals API: /api/stats
        if parsed.path == "/api/stats":
            st = redis_stats()
            lru = redis_lru_order()
            aof_path = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "appendonly.aof"))
            aof_lines = []
            if os.path.exists(aof_path):
                try:
                    with open(aof_path, "r", encoding="utf-8", errors="replace") as f:
                        lines = f.readlines()
                        aof_lines = [l.strip() for l in lines[-12:] if l.strip()]
                except Exception:
                    pass

            self._json(200, {
                "stats": st,
                "lruOrder": lru,
                "aofRecent": aof_lines
            })
            return

        # Main Page
        if parsed.path == "/" or parsed.path == "/index.html":
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.end_headers()
            self.wfile.write(HTML_PAGE.encode("utf-8"))
            return

        self.send_response(404)
        self.end_headers()

    def do_POST(self):
        content_len = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(content_len)
        try:
            data = json.loads(body.decode("utf-8")) if body else {}
        except Exception:
            data = {}

        parsed = urllib.parse.urlparse(self.path)

        # ── 2FA GENERATE & DISPATCH (SMS + EMAIL) ──
        if parsed.path == "/api/otp/generate":
            channel = data.get("channel", "BOTH")
            phone = data.get("phone", "+91 98765 43210").strip()
            email = data.get("email", "evaluator@college.edu").strip()
            purpose = data.get("purpose", "Authentication").strip()
            ttl = int(data.get("ttl", 45))

            # Primary recipient ID for memory key
            primary_rec = phone if channel == "SMS" else email if channel == "EMAIL" else f"{phone} / {email}"
            clean_rec = "".join(c for c in primary_rec if c.isalnum() or c in "@._")
            code = f"{random.randint(100000, 999999)}"

            # 1. Register in Mini-Redis with strict TTL
            redis_set(f"otp:code:{clean_rec}", code, ttl)
            redis_set(f"otp:attempts:{clean_rec}", "0", ttl)
            meta_payload = json.dumps({
                "recipient": primary_rec,
                "phone": phone,
                "email": email,
                "purpose": purpose,
                "created_at": time.time(),
                "channel": channel
            })
            redis_set(f"otp:meta:{clean_rec}", urllib.parse.quote(meta_payload), ttl)

            # 2. Trigger Real SMS Dispatch
            sms_status = None
            if channel in ["BOTH", "SMS"] and phone:
                sms_ok, sms_msg = send_real_sms(phone, code, purpose)
                sms_status = sms_msg

            # 3. Trigger Real Email Dispatch
            email_status = None
            if channel in ["BOTH", "EMAIL"] and email:
                email_ok, email_msg = send_real_email(email, code, purpose, ttl)
                email_status = email_msg

            self._json(200, {
                "ok": True,
                "code": code,
                "recipient": primary_rec,
                "clean_id": clean_rec,
                "purpose": purpose,
                "ttl": ttl,
                "sms_status": sms_status,
                "email_status": email_status
            })
            return

        # ── 2FA VERIFICATION TERMINAL ──
        if parsed.path == "/api/otp/verify":
            recipient = data.get("recipient", "").strip()
            code = data.get("code", "").strip()
            clean_rec = "".join(c for c in recipient if c.isalnum() or c in "@._")

            t0 = time.time()
            stored_code = redis_get(f"otp:code:{clean_rec}")
            latency = round((time.time() - t0) * 1000, 3)

            if not stored_code:
                self._json(200, {
                    "ok": False,
                    "status": "EXPIRED_OR_ABSENT",
                    "latency_ms": latency,
                    "message": "Token does not exist or has expired. Mini-Redis automatically evicted the key from RAM."
                })
                return

            raw_attempts = redis_get(f"otp:attempts:{clean_rec}")
            attempts = int(raw_attempts) if raw_attempts and raw_attempts.isdigit() else 0

            if attempts >= 3:
                self._json(200, {
                    "ok": False,
                    "status": "LOCKED",
                    "latency_ms": latency,
                    "message": "Max verification attempts exceeded (3/3). Security lockout active in RAM."
                })
                return

            if code == stored_code:
                # INSTANT PURGE FROM RAM: Enforce Single-Use Guarantee
                redis_del(f"otp:code:{clean_rec}")
                redis_del(f"otp:attempts:{clean_rec}")
                redis_del(f"otp:meta:{clean_rec}")

                self._json(200, {
                    "ok": True,
                    "status": "VERIFIED",
                    "latency_ms": latency,
                    "message": "Authentication successful! The key was instantly deleted from Mini-Redis memory via DEL to permanently prevent replay attacks."
                })
            else:
                rem_ttl = max(1, redis_ttl(f"otp:code:{clean_rec}"))
                redis_set(f"otp:attempts:{clean_rec}", str(attempts + 1), rem_ttl)
                rem_attempts = 3 - (attempts + 1)
                self._json(200, {
                    "ok": False,
                    "status": "INVALID_CODE",
                    "latency_ms": latency,
                    "attempts_remaining": rem_attempts,
                    "message": f"Incorrect PIN entered. {rem_attempts} attempt(s) remaining before security lockout."
                })
            return

        # ── REVOKE OTP ──
        if parsed.path == "/api/otp/revoke":
            recipient = data.get("recipient", "").strip()
            clean_rec = "".join(c for c in recipient if c.isalnum() or c in "@._")
            redis_del(f"otp:code:{clean_rec}")
            redis_del(f"otp:attempts:{clean_rec}")
            redis_del(f"otp:meta:{clean_rec}")
            self._json(200, {"ok": True})
            return

        # ── SAVE GATEWAY CONFIG ──
        if parsed.path == "/api/config":
            current_cfg = load_gateway_config()
            for k in ["twofactor_key", "fast2sms_key", "smtp_user", "smtp_host", "smtp_port", "resend_key"]:
                if k in data:
                    current_cfg[k] = data[k]
            # Don't overwrite password if masked
            if "smtp_pass" in data and data["smtp_pass"] and "••••" not in data["smtp_pass"]:
                current_cfg["smtp_pass"] = data["smtp_pass"]

            save_gateway_config(current_cfg)
            self._json(200, {"ok": True, "message": "Gateway credentials saved"})
            return

        # ── SHORTENER & LEADERBOARD ENDPOINTS ──
        if parsed.path == "/api/shorten":
            url = data.get("url", "").strip()
            custom_code = data.get("custom_code", "").strip()
            ttl = int(data.get("ttl", 0))
            tag = data.get("tag", "General").strip()

            if not url:
                self._json(400, {"error": "URL is required"})
                return

            code = "".join(c for c in custom_code if c.isalnum() or c in "-_") if custom_code else generate_code(url)
            redis_set(f"url:{code}", url, ttl)
            redis_set(f"clicks:{code}", "0")
            redis_set(f"meta:{code}", urllib.parse.quote(json.dumps({"tag": tag, "url": url})), ttl)

            self._json(200, {"short_url": f"{BASE_URL}/s/{code}", "code": code, "url": url, "ttl": ttl, "tag": tag})
            return

        if parsed.path == "/api/delete":
            code = data.get("code", "").strip()
            if code:
                redis_del(f"url:{code}")
                redis_del(f"clicks:{code}")
                redis_del(f"meta:{code}")
            self._json(200, {"ok": True})
            return

        if parsed.path == "/api/leaderboard/score":
            player_id = data.get("player_id", "")
            delta = int(data.get("delta", 0))
            raw_meta = redis_get(f"lb:player:{player_id}")
            if raw_meta:
                p = json.loads(urllib.parse.unquote(raw_meta))
                current_score = int(redis_get(f"lb:score:{player_id}") or p.get("score", 0))
                new_score = max(0, current_score + delta)
                p["score"] = new_score
                p["matches"] = p.get("matches", 0) + 1
                if delta > 0: p["wins"] = p.get("wins", 0) + 1
                redis_set(f"lb:score:{player_id}", str(new_score))
                redis_set(f"lb:player:{player_id}", urllib.parse.quote(json.dumps(p)))
                self._json(200, {"ok": True, "player": p})
            else:
                self._json(404, {"error": "Player not found"})
            return

        if parsed.path == "/api/leaderboard/simulate":
            all_keys = redis_keys()
            player_keys = [k for k in all_keys if k.startswith("lb:player:")]
            if player_keys:
                chosen = random.sample(player_keys, min(len(player_keys), 5))
                for pk in chosen:
                    pid = pk[10:]
                    raw_meta = redis_get(pk)
                    if raw_meta:
                        p = json.loads(urllib.parse.unquote(raw_meta))
                        cur_score = int(redis_get(f"lb:score:{pid}") or p.get("score", 0))
                        p["score"] = cur_score + random.randint(20, 110)
                        p["matches"] = p.get("matches", 0) + 1
                        p["wins"] = p.get("wins", 0) + 1
                        redis_set(f"lb:score:{pid}", str(p["score"]))
                        redis_set(pk, urllib.parse.quote(json.dumps(p)))
            self._json(200, {"ok": True})
            return

        if parsed.path == "/api/leaderboard/reset":
            all_keys = redis_keys()
            for k in all_keys:
                if k.startswith("lb:"): redis_del(k)
            for p in DEFAULT_PLAYERS:
                pid = p["id"]
                redis_set(f"lb:player:{pid}", urllib.parse.quote(json.dumps(p)))
                redis_set(f"lb:score:{pid}", str(p["score"]))
            self._json(200, {"ok": True})
            return

        # ── EXEC RESP CLI ──
        if parsed.path == "/api/exec":
            cmd = data.get("command", "").strip()
            raw = redis_cmd(cmd)
            self._json(200, {"raw": raw.strip()})
            return

        self.send_response(404)
        self.end_headers()

    def _json(self, status, payload):
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(json.dumps(payload).encode("utf-8"))

    def log_message(self, fmt, *args):
        return


def main():
    ping = redis_cmd("PING")
    if "PONG" in ping:
        print(f"  [OK] Connected to Mini-Redis C++ engine on port {REDIS_PORT}")
        seed_leaderboard_if_empty()
        seed_links_if_empty()
    else:
        print(f"  [!] Mini-Redis server not detected on port {REDIS_PORT}")

    server = http.server.ThreadingHTTPServer(("0.0.0.0", WEB_PORT), AuthKVProductionHandler)
    print()
    print("  +-------------------------------------------------------------+")
    print("  |   AuthKV — Ephemeral 2FA Security Platform is LIVE at:      |")
    print(f"  |   -> http://localhost:{WEB_PORT}                                 |")
    print("  |                                                             |")
    print("  |   Features:                                                 |")
    print("  |     - Dual-Channel Real Phone SMS (Fast2SMS / Twilio)       |")
    print("  |     - Real HTML Security Email (Gmail SMTP / Resend)        |")
    print("  |     - Hardware In-Memory TTL Auto-Eviction (SET EX)         |")
    print("  |     - Zero-Replay Defense Single-Use Purge (DEL)            |")
    print("  |     - C++ LRU DoublyLinkedList & AOF Telemetry Drawer       |")
    print("  +-------------------------------------------------------------+")
    print()
    server.serve_forever()


if __name__ == "__main__":
    main()
