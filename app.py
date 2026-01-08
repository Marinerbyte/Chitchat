import os
import json
import time
import threading
import random
import websocket
import ssl
import requests
import textdistance
import emoji
from flask import Flask, render_template_string, request, jsonify
from openai import OpenAI
from fuzzywuzzy import fuzz
from datetime import datetime

# ================= ⚙️ GLOBAL CONFIGURATION =================
app = Flask(__name__)
GROQ_API_KEY = os.environ.get("GROQ_API_KEY") 

groq_client = OpenAI(base_url="https://api.groq.com/openai/v1", api_key=GROQ_API_KEY)

# 📱 2026 TRICK: Real Device Fingerprints
USER_AGENTS = [
    "Mozilla/5.0 (Linux; Android 14; SM-S918B) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.6099.144 Mobile Safari/537.36",
    "Mozilla/5.0 (iPhone; CPU iPhone OS 17_3 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.3 Mobile/15E148 Safari/604.1",
    "Mozilla/5.0 (Linux; Android 13; Pixel 8 Pro) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.6167.101 Mobile Safari/537.36"
]

# Shared System State
SYSTEM_STATE = {
    "password": "", 
    "room_name": "testroom", 
    "running": False,
    "topics": [
        "best thriller movies on netflix", "bangalore traffic nightmare", "virat kohli's captaincy",
        "office jobs vs freelancing", "street food hygiene", "planning a goa trip",
        "funny childhood punishments", "expensive weddings logic", "gym motivation struggles"
    ],
    "current_topic": "general chit-chat"
}

CHAT_MEMORY = [] # Context for AI
LOGS = [] # Debugging Logs

# ================= 🧠 INTELLIGENCE & HUMANIZER ENGINE =================

class Humanizer:
    @staticmethod
    def introduce_typos(text):
        """Randomly swaps characters to simulate human error (3% chance)"""
        if random.random() > 0.04: return text # 96% accuracy
        if len(text) < 5: return text
        
        # Swap two characters
        idx = random.randint(0, len(text) - 2)
        chars = list(text)
        chars[idx], chars[idx+1] = chars[idx+1], chars[idx]
        return "".join(chars)

    @staticmethod
    def add_slang(text):
        """Converts formal words to Hinglish slang"""
        replacements = {
            "yes": "haa", "no": "nahi", "really": "sahi me", "brother": "bhai",
            "okay": "thik hai", "good": "mast", "bad": "bekar", "laugh": "lol"
        }
        words = text.split()
        return " ".join([replacements.get(w.lower(), w) for w in words])

    @staticmethod
    def burst_split(text):
        """Splits long messages into two (Double Texting)"""
        if len(text) > 30 and random.random() < 0.35:
            for sep in [',', ' aur ', ' but ', ' par ']:
                if sep in text:
                    parts = text.split(sep, 1)
                    return [parts[0].strip(), (sep.strip() + " " + parts[1]).strip()]
        return [text]

def get_smart_reply(sender, partner, memory):
    """Generates Reply -> Checks Dupes -> Humanizes"""
    history = "\n".join([f"{m['s']}: {m['t']}" for m in memory[-6:]])
    prompt = f"""
    Act as {sender}. Chatting with {partner}.
    Topic: {SYSTEM_STATE['current_topic']}
    History:
    {history}
    
    Directives:
    - Casual Hinglish (Roman Hindi).
    - Short, punchy sentences.
    - No repetitions. No "I am AI".
    """
    
    for _ in range(2):
        try:
            resp = groq_client.chat.completions.create(
                model="llama3-8b-instant", messages=[{"role": "user", "content": prompt}], max_tokens=60, temperature=1.15
            )
            raw = resp.choices[0].message.content.replace(f"{sender}:", "").replace('"', '').strip()
            
            # Dupe Check
            if any(fuzz.ratio(raw.lower(), m['t'].lower()) > 80 for m in memory[-10:]): continue
            
            # Humanize
            processed = Humanizer.add_slang(raw)
            processed = Humanizer.introduce_typos(processed)
            
            # Emoji Polish
            if emoji.emoji_count(processed) == 0:
                keywords = {'lol':'😂','bhai':'🤝','sad':'🥲','love':'❤️','angry':'😡'}
                for k,v in keywords.items():
                    if k in processed.lower(): processed += " " + v; break
            
            return processed
        except: time.sleep(1)
    return "Haa bhai sahi bola 👍"

# ================= 🤖 THE ROBUST BOT CLASS =================

class SmartBot:
    def __init__(self, username, partner_name):
        self.username = username
        self.partner = partner_name
        self.token = None
        self.ws = None
        self.room_id = None
        self.ua = random.choice(USER_AGENTS) # Unique fingerprint
        self.reconnect_count = 0

    def log(self, msg, type="INFO"):
        t = datetime.now().strftime("%H:%M:%S")
        entry = f"[{t}] [{type}] [{self.username}] {msg}"
        print(entry)
        LOGS.append(entry)
        if len(LOGS) > 300: LOGS.pop(0)

    def login(self):
        """Http Login with Spoofed Headers"""
        headers = {
            "User-Agent": self.ua,
            "Content-Type": "application/json",
            "Origin": "https://howdies.app",
            "Referer": "https://howdies.app/login"
        }
        try:
            r = requests.post(
                "https://api.howdies.app/api/login", 
                json={"username": self.username, "password": SYSTEM_STATE['password']},
                headers=headers, timeout=15
            )
            if r.status_code == 200:
                data = r.json()
                self.token = data.get("token") or data.get("data", {}).get("token")
                return True
        except Exception as e:
            self.log(f"Login Error: {e}", "ERROR")
        return False

    def connect(self):
        """Persistent WebSocket Connection Logic"""
        if not self.token:
            if not self.login(): return

        ws_url = f"wss://app.howdies.app/howdies?token={self.token}"
        self.ws = websocket.WebSocketApp(
            ws_url,
            header={"User-Agent": self.ua}, # 2026 Trick: WS Headers
            on_open=self.on_open,
            on_message=self.on_message,
            on_error=self.on_error,
            on_close=self.on_close
        )
        
        # Run in a separate thread so it doesn't block
        threading.Thread(target=self.ws.run_forever, kwargs={"sslopt": {"cert_reqs": ssl.CERT_NONE}}, daemon=True).start()

    def on_open(self, ws):
        self.log("Connected to Socket", "NET")
        self.reconnect_count = 0
        # 1. Auth
        ws.send(json.dumps({"handler": "login", "username": self.username, "password": SYSTEM_STATE['password']}))
        time.sleep(1)
        # 2. Join Room
        ws.send(json.dumps({
            "handler": "joinchatroom", "id": str(time.time()), 
            "name": SYSTEM_STATE['room_name'], "roomPassword": ""
        }))
        # 3. Start Heartbeat (To keep connection alive)
        threading.Thread(target=self.heartbeat, daemon=True).start()

    def on_message(self, ws, msg):
        if not SYSTEM_STATE['running']: return
        try:
            d = json.loads(msg)
            # Room ID Capture
            if d.get("handler") == "joinchatroom" and d.get("roomid"):
                self.room_id = d["roomid"]
                self.log(f"Joined Room ID: {self.room_id}", "SUCCESS")

            # Chat Handling
            if d.get("handler") in ["chatroommessage", "message"]:
                sender = d.get("from") or d.get("username")
                text = d.get("text")
                if sender and text:
                    # Update Memory
                    if not CHAT_MEMORY or CHAT_MEMORY[-1]['t'] != text:
                        CHAT_MEMORY.append({"s": sender, "t": text, "time": datetime.now().strftime("%H:%M")})
                        if len(CHAT_MEMORY) > 20: CHAT_MEMORY.pop(0)

                    # Reactive Logic: If PARTNER speaks, I reply
                    if sender == self.partner:
                        threading.Thread(target=self.process_reply, args=(text,)).start()
        except: pass

    def on_error(self, ws, err):
        self.log(f"Socket Error: {err}", "ERROR")

    def on_close(self, ws, close_status_code, close_msg):
        self.log("Disconnected. Attempting Reconnect in 5s...", "WARN")
        time.sleep(5)
        if SYSTEM_STATE['running']:
            self.connect() # Auto Reconnect Loop

    def heartbeat(self):
        """Sends a Ping every 30s to prevent server disconnect"""
        while self.ws and self.ws.sock and self.ws.sock.connected:
            time.sleep(30)
            try:
                # Some servers accept empty JSON or ping handler
                self.ws.send(json.dumps({"handler": "ping"}))
            except: break

    def process_reply(self, incoming_text):
        """The Human Simulation Pipeline"""
        # 1. Read Delay (Thinking Time)
        read_time = len(incoming_text) * 0.05 + random.uniform(2, 5)
        time.sleep(read_time)
        
        if not SYSTEM_STATE['running']: return

        # 2. Brain Work
        reply_text = get_smart_reply(self.username, self.partner, CHAT_MEMORY)
        
        # 3. Burst Splitting (Double Texting)
        messages = Humanizer.burst_split(reply_text)

        # 4. Typing & Sending
        for msg in messages:
            type_time = len(msg) * 0.15 # Typing speed
            self.log(f"Typing... ({type_time:.1f}s)", "TYPING")
            time.sleep(type_time)
            
            if self.ws and self.room_id:
                pkt = {
                    "handler": "chatroommessage", "id": str(time.time()),
                    "type": "text", "roomid": self.room_id, "text": msg, "url": "", "length": "0"
                }
                self.ws.send(json.dumps(pkt))
                self.log(f"Sent: {msg}", "CHAT")

# ================= 🎛️ CONTROLLER LOGIC =================
BOT_INSTANCES = {}

def start_system(u1, u2, pwd, room):
    SYSTEM_STATE.update({"password": pwd, "room_name": room, "running": True})
    
    # Initialize Bots
    BOT_INSTANCES["1"] = SmartBot(u1, u2)
    BOT_INSTANCES["2"] = SmartBot(u2, u1)
    
    # Connect
    BOT_INSTANCES["1"].connect()
    BOT_INSTANCES["2"].connect()
    
    # Auto-Kickstart Conversation
    threading.Thread(target=auto_kickstart, daemon=True).start()
    
    # Auto-Maintanence
    threading.Thread(target=maintenance_loop, daemon=True).start()

def stop_system():
    SYSTEM_STATE["running"] = False
    for b in BOT_INSTANCES.values():
        if b.ws: b.ws.close()
    BOT_INSTANCES.clear()

def auto_kickstart():
    """Bot 1 starts the chat after 10s"""
    time.sleep(10)
    b1 = BOT_INSTANCES.get("1")
    if b1 and b1.room_id and SYSTEM_STATE['running']:
        starters = [
            f"Aur bhai {b1.partner}, kidhar gayab hai?", 
            f"Oye {b1.partner}, aaj ka match dekha kya?",
            "Bhai badi bhook lagi hai kuch order karein?"
        ]
        msg = random.choice(starters)
        b1.ws.send(json.dumps({
            "handler": "chatroommessage", "id": str(time.time()),
            "type": "text", "roomid": b1.room_id, "text": msg, "url": "", "length": "0"
        }))
        b1.log(f"🚀 Kicked off chat: {msg}", "SYSTEM")

def maintenance_loop():
    """Rotates topics and cleans logs"""
    while SYSTEM_STATE['running']:
        time.sleep(900) # 15 mins
        LOGS.clear()
        SYSTEM_STATE['current_topic'] = random.choice(SYSTEM_STATE['topics'])
        log_sys(f"Topic Changed to: {SYSTEM_STATE['current_topic']}")

def log_sys(msg):
    LOGS.append(f"[{datetime.now().strftime('%H:%M:%S')}] [SYSTEM] {msg}")

# ================= 🖥️ FLASK UI =================
HTML_UI = """
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <title>ULTIMATE BOT 2026</title>
    <style>
        body { background: #0a0a0a; color: #00ff00; font-family: 'Consolas', monospace; padding: 20px; }
        .panel { border: 1px solid #333; background: #111; padding: 20px; border-radius: 8px; margin-bottom: 15px; box-shadow: 0 0 10px rgba(0,255,0,0.1); }
        h2 { margin-top: 0; color: #fff; border-bottom: 1px solid #333; padding-bottom: 10px; }
        .grid { display: grid; grid-template-columns: 1fr 1fr; gap: 15px; }
        label { color: #888; font-size: 12px; display: block; margin-bottom: 5px; }
        input { width: 100%; padding: 12px; background: #000; border: 1px solid #444; color: #fff; border-radius: 4px; box-sizing: border-box; }
        input:focus { border-color: #00ff00; outline: none; }
        button { width: 100%; padding: 15px; border: none; font-weight: bold; cursor: pointer; border-radius: 4px; font-size: 14px; transition: 0.2s; }
        .btn-start { background: linear-gradient(45deg, #006400, #00ff00); color: #000; }
        .btn-start:hover { box-shadow: 0 0 15px #00ff00; }
        .btn-stop { background: linear-gradient(45deg, #500, #f00); color: white; }
        #console { height: 400px; overflow-y: auto; background: #000; border: 1px solid #333; padding: 10px; font-size: 12px; line-height: 1.4; }
        
        /* Log Colors */
        .l-CHAT { color: #00ffff; }
        .l-TYPING { color: #ff00ff; }
        .l-ERROR { color: #ff3333; }
        .l-SYSTEM { color: #ffff00; }
        .l-NET { color: #888; }
        
        ::-webkit-scrollbar { width: 8px; }
        ::-webkit-scrollbar-thumb { background: #333; border-radius: 4px; }
    </style>
</head>
<body>
    <div class="panel">
        <h2>☢️ ULTIMATE HUMAN-BOT CONTROLLER (v2026)</h2>
        <div class="grid">
            <div><label>BOT 1 USERNAME</label><input id="u1" placeholder="e.g. RajKiller"></div>
            <div><label>BOT 2 USERNAME</label><input id="u2" placeholder="e.g. SimranCool"></div>
        </div>
        <br>
        <div class="grid">
            <div><label>COMMON PASSWORD</label><input id="p" type="password" placeholder="••••••"></div>
            <div><label>ROOM NAME</label><input id="r" value="vip_lounge"></div>
        </div>
        <br>
        <div class="grid">
            <button class="btn-start" onclick="cmd('start')">🚀 INITIALIZE SYSTEM</button>
            <button class="btn-stop" onclick="cmd('stop')">💀 TERMINATE SEQUENCE</button>
        </div>
    </div>

    <div class="panel">
        <label>LIVE NEURAL NETWORK LOGS</label>
        <div id="console"></div>
    </div>

    <script>
        function cmd(act) {
            const payload = {
                a: act,
                u1: document.getElementById('u1').value,
                u2: document.getElementById('u2').value,
                p: document.getElementById('p').value,
                r: document.getElementById('r').value
            };
            fetch('/cmd', {
                method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify(payload)
            }).then(r=>r.json()).then(d=>alert(d.msg));
        }

        setInterval(() => {
            fetch('/logs').then(r=>r.json()).then(d => {
                const c = document.getElementById('console');
                const scroll = c.scrollTop === c.scrollHeight - c.clientHeight;
                
                c.innerHTML = d.logs.map(line => {
                    let cls = 'l-INFO';
                    if(line.includes('[CHAT]')) cls = 'l-CHAT';
                    if(line.includes('[TYPING]')) cls = 'l-TYPING';
                    if(line.includes('[ERROR]')) cls = 'l-ERROR';
                    if(line.includes('[SYSTEM]')) cls = 'l-SYSTEM';
                    if(line.includes('[NET]')) cls = 'l-NET';
                    return `<div class="${cls}">${line}</div>`;
                }).join('');
                
                if(scroll) c.scrollTop = c.scrollHeight;
            });
        }, 1000);
    </script>
</body>
</html>
"""

@app.route('/')
def index(): return render_template_string(HTML_UI)

@app.route('/cmd', methods=['POST'])
def command():
    d = request.json
    if d['a'] == 'stop':
        stop_system()
        return jsonify({"msg": "System Shutdown."})
    
    if not (d['u1'] and d['u2'] and d['p']):
        return jsonify({"msg": "Missing Credentials!"})
        
    start_system(d['u1'], d['u2'], d['p'], d['r'])
    return jsonify({"msg": "System Initialized. Watch Logs."})

@app.route('/logs')
def get_logs(): return jsonify({"logs": LOGS})

if __name__ == '__main__':
    port = int(os.environ.get("PORT", 5000))
    app.run(host='0.0.0.0', port=port)
