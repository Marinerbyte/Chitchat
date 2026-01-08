import os
import json
import time
import threading
import random
import websocket
import ssl
import requests
import psycopg2
from flask import Flask, render_template_string, request, jsonify
from openai import OpenAI
from fuzzywuzzy import fuzz
from datetime import datetime

app = Flask(__name__)

# ================= 🔧 CONFIGURATION =================
GROQ_API_KEY = os.environ.get("GROQ_API_KEY")
NEON_DB_URL = os.environ.get("NEON_DB_URL") 

try:
    groq_client = OpenAI(base_url="https://api.groq.com/openai/v1", api_key=GROQ_API_KEY)
except:
    print("❌ Groq API Key missing or invalid.")

SYSTEM_STATE = {"password": "", "room_name": "", "running": False}
LOGS = []
BOT_INSTANCES = {}
SESSION_RAM = {}

# Stealth Fingerprints
REAL_DEVICES = [
    "Mozilla/5.0 (Linux; Android 14; SM-S918B) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.6099.144 Mobile Safari/537.36",
    "Mozilla/5.0 (iPhone; CPU iPhone OS 17_4 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.4 Mobile/15E148 Safari/604.1"
]

# ================= 🧠 SOCIAL BRAIN & MEMORY =================

def save_memory(bot_name, user, message, role):
    now = time.time()
    if user not in SESSION_RAM:
        SESSION_RAM[user] = {
            'msgs': [], 'last_active': now, 'is_vip': False,
            'battery': 100.0, 'mood': 'chill'
        }
    
    data = SESSION_RAM[user]
    data['last_active'] = now

    # Update Mood based on keywords (Emotional Inertia)
    if role == "user":
        t = message.lower()
        if any(x in t for x in ['haha', 'lol', '😂', 'funny']): data['mood'] = 'playful'
        elif any(x in t for x in ['yaar', 'bhai', 'dost']): data['mood'] = 'friendly'
        elif any(x in t for x in ['?', 'kyu', 'kab', 'kaun']): data['mood'] = 'curious'
        elif any(x in t for x in ['chup', 'ignore', 'bekar', 'gussa']): data['mood'] = 'moody'
    
    # Drain Battery when bot talks
    if role == "assistant":
        data['battery'] -= random.uniform(8, 15)

    data['msgs'].append({"role": role, "content": message})
    if len(data['msgs']) > 10: data['msgs'].pop(0)

def battery_recharger():
    """Background thread: Recover energy over time even when silent"""
    while True:
        time.sleep(60)
        for user in list(SESSION_RAM.keys()):
            SESSION_RAM[user]['battery'] = min(100.0, SESSION_RAM[user]['battery'] + 3.0)

threading.Thread(target=battery_recharger, daemon=True).start()

# ================= 🎭 HUMANIZER & LOGIC =================

def get_smart_reply(bot_name, target_user, message, is_partner):
    data = SESSION_RAM.get(target_user, {'battery': 100, 'mood': 'chill', 'msgs': []})
    
    # 1. Social Decision (Should I reply?)
    if not is_partner:
        # If battery is low, ignore non-partners 80% of the time
        if data['battery'] < 30 and random.random() < 0.8: return None
        # Normal randomness (not always replying to strangers)
        if random.random() < 0.4: return None

    # 2. Generate Reply
    effort = "lazy and short" if data['battery'] < 40 else "normal and Hinglish"
    prompt = (
        f"You are {bot_name}. Friend of {target_user}. "
        f"Current Mood: {data['mood']}. Energy: {effort}. "
        "Rules: Casual Hinglish. Never sound like a bot. Silence is okay. No formal apologies."
    )

    history = data['msgs'][-6:]
    try:
        resp = groq_client.chat.completions.create(
            model="llama3-8b-instant",
            messages=[{"role": "system", "content": prompt}] + history,
            max_tokens=60, temperature=1.2
        )
        reply = resp.choices[0].message.content.strip().replace(f"{bot_name}:", "").replace('"', '')

        # 3. Anti-Loop (Fuzzy Check)
        for m in history:
            if fuzz.ratio(reply.lower(), m['content'].lower()) > 80: return None
            
        return reply
    except: return None

# ================= 🤖 SMART BOT CLASS =================

class SmartBot:
    def __init__(self, username, partner_name):
        self.username = username
        self.partner = partner_name
        self.token = None
        self.ws = None
        self.room_id = None
        self.ua = random.choice(REAL_DEVICES)

    def log(self, msg, type="INFO"):
        t = datetime.now().strftime("%H:%M:%S")
        LOGS.append(f"[{t}] [{type}] [{self.username}] {msg}")
        if len(LOGS) > 100: LOGS.pop(0)

    def login(self):
        headers = {"User-Agent": self.ua, "Content-Type": "application/json"}
        try:
            r = requests.post("https://api.howdies.app/api/login", 
                json={"username": self.username, "password": SYSTEM_STATE['password']}, 
                headers=headers, timeout=10)
            if r.status_code == 200:
                self.token = r.json().get("token") or r.json().get("data", {}).get("token")
                return True
        except: pass
        return False

    def send_ws(self, handler, data):
        if self.ws and self.ws.sock and self.ws.sock.connected:
            payload = {"handler": handler, "id": str(time.time())}
            payload.update(data)
            self.ws.send(json.dumps(payload))

    def on_message(self, ws, msg):
        if not SYSTEM_STATE['running']: return
        try:
            d = json.loads(msg)
            if d.get("handler") == "joinchatroom": self.room_id = d.get("roomid")
            if d.get("handler") in ["chatroommessage", "message"]:
                sender = d.get("from") or d.get("username")
                text = d.get("text", "")
                if not sender or sender == self.username: return

                is_partner = (sender == self.partner)
                save_memory(self.username, sender, text, "user")
                
                # Randomized Thinking Delay
                threading.Thread(target=self.process_logic, args=(sender, text, is_partner)).start()
        except: pass

    def process_logic(self, sender, text, is_partner):
        # Human-like thinking pause
        time.sleep(random.uniform(3, 8))
        
        reply = get_smart_reply(self.username, sender, text, is_partner)
        if reply and SYSTEM_STATE['running']:
            # Typing Indicator
            self.send_ws("starttyping", {"roomid": self.room_id})
            # Typing speed simulation
            time.sleep(len(reply) * random.uniform(0.08, 0.15))
            
            self.send_ws("chatroommessage", {
                "type": "text", "roomid": self.room_id, "text": reply, "url": "", "length": "0"
            })
            save_memory(self.username, sender, reply, "assistant")
            self.log(f"Sent: {reply}", "CHAT")

    def connect(self):
        if not self.token and not self.login(): 
            self.log("Login Failed", "ERROR")
            return
        
        def run():
            self.ws = websocket.WebSocketApp(
                f"wss://app.howdies.app/howdies?token={self.token}",
                header={"User-Agent": self.ua},
                on_open=lambda ws: self.send_ws("joinchatroom", {"name": SYSTEM_STATE['room_name'], "roomPassword": ""}),
                on_message=self.on_message,
                on_close=lambda ws, a, b: self.reconnect()
            )
            self.ws.run_forever(sslopt={"cert_reqs": ssl.CERT_NONE})
        
        threading.Thread(target=run, daemon=True).start()

    def reconnect(self):
        if SYSTEM_STATE['running']:
            time.sleep(10)
            self.connect()

# ================= ⚡ FLASK CONTROL PANEL =================

@app.route('/cmd', methods=['POST'])
def cmd():
    d = request.json
    if d['a'] == 'start':
        SYSTEM_STATE.update({"password": d['p'], "room_name": d['r'], "running": True})
        BOT_INSTANCES["1"] = SmartBot(d['u1'], d['u2'])
        BOT_INSTANCES["2"] = SmartBot(d['u2'], d['u1'])
        BOT_INSTANCES["1"].connect()
        BOT_INSTANCES["2"].connect()
        return jsonify({"msg": "Both bots connected!"})
    elif d['a'] == 'stop':
        SYSTEM_STATE['running'] = False
        for b in BOT_INSTANCES.values():
            if b.ws: b.ws.close()
        return jsonify({"msg": "Bots disconnected."})
    return jsonify({"msg": "Invalid action"})

@app.route('/logs')
def get_logs(): return jsonify({"logs": LOGS})

@app.route('/')
def index():
    return render_template_string(HTML_UI)

HTML_UI = """
<!DOCTYPE html>
<html>
<head>
    <title>Master Bot V5</title>
    <style>
        body{background:#0a0a0a;color:#0f0;font-family:monospace;padding:20px}
        .box{border:1px solid #333;padding:15px;margin-bottom:15px;background:#111}
        input{background:#000;border:1px solid #0f0;color:#fff;padding:8px;margin:5px;width:150px}
        button{padding:10px;cursor:pointer;background:#0f0;color:#000;border:none;font-weight:bold}
        #console{height:300px;overflow-y:auto;background:#000;padding:10px;border:1px solid #222}
        .l-CHAT{color:#00ffff} .l-ERROR{color:red}
    </style>
</head>
<body>
    <div class="box">
        <h3>🚀 Master Bot V5 (Social Brain Active)</h3>
        <input id="u1" placeholder="Bot 1 Name">
        <input id="u2" placeholder="Bot 2 Name">
        <input id="p" type="password" placeholder="Password">
        <input id="r" placeholder="Room Name">
        <button onclick="act('start')">START</button>
        <button style="background:red;color:white" onclick="act('stop')">STOP</button>
    </div>
    <div class="box" id="console"></div>
    <script>
        function act(a){
            fetch('/cmd',{method:'POST',headers:{'Content-Type':'application/json'},
            body:JSON.stringify({a:a,u1:document.getElementById('u1').value,u2:document.getElementById('u2').value,p:document.getElementById('p').value,r:document.getElementById('r').value})})
            .then(r=>r.json()).then(d=>alert(d.msg));
        }
        setInterval(()=>{
            fetch('/logs').then(r=>r.json()).then(d=>{
                const c=document.getElementById('console');
                c.innerHTML=d.logs.map(l=>`<div class="l-${l.split(']')[1]?.trim()}">${l}</div>`).join('');
                c.scrollTop=c.scrollHeight;
            })
        },2000);
    </script>
</body>
</html>
"""

if __name__ == '__main__':
    # Yeh raha aapka missing port handling
    port = int(os.environ.get("PORT", 5000))
    app.run(host='0.0.0.0', port=port)
