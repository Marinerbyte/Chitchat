import os
import json
import time
import threading
import random
import websocket
import ssl
import requests
from flask import Flask, render_template_string, request, jsonify
from openai import OpenAI
from fuzzywuzzy import fuzz
from datetime import datetime

app = Flask(__name__)

# ================= 🔧 CONFIGURATION =================
GROQ_API_KEY = os.environ.get("GROQ_API_KEY")
# Neon DB logic is optional; using SESSION_RAM for stability in this build
try:
    groq_client = OpenAI(base_url="https://api.groq.com/openai/v1", api_key=GROQ_API_KEY)
except:
    print("⚠️ Groq API Key not found.")

SYSTEM_STATE = {"password": "", "room_name": "", "running": False}
LOGS = []
BOT_INSTANCES = {}
SESSION_RAM = {}

# Stealth: Real Android/iOS User-Agents
REAL_DEVICES = [
    "Mozilla/5.0 (Linux; Android 14; SM-S918B) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.6099.144 Mobile Safari/537.36",
    "Mozilla/5.0 (iPhone; CPU iPhone OS 17_4 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.4 Mobile/15E148 Safari/604.1"
]

# ================= 🧠 SOCIAL BRAIN & MEMORY =================

def save_memory(bot_name, user, message, role):
    now = time.time()
    if user not in SESSION_RAM:
        SESSION_RAM[user] = {
            'msgs': [], 'last_active': now, 
            'battery': 100.0, 'mood': 'chill'
        }
    
    data = SESSION_RAM[user]
    data['last_active'] = now

    # Update Mood (Emotional Carryover)
    if role == "user":
        t = message.lower()
        if any(x in t for x in ['haha', 'lol', '😂', 'funny']): data['mood'] = 'playful'
        elif any(x in t for x in ['pyaar', 'love', '❤️', 'miss']): data['mood'] = 'sweet'
        elif any(x in t for x in ['?', 'kyu', 'kaise']): data['mood'] = 'curious'
        elif any(x in t for x in ['chup', 'hat', 'bekar', 'ignore']): data['mood'] = 'annoyed'
    
    # Drain Battery (Fatigue)
    if role == "assistant":
        data['battery'] -= random.uniform(8, 15)

    data['msgs'].append({"role": role, "content": message})
    if len(data['msgs']) > 8: data['msgs'].pop(0)

def battery_recharger():
    """Energy recovers naturally when the bot is silent"""
    while True:
        time.sleep(60)
        for user in list(SESSION_RAM.keys()):
            SESSION_RAM[user]['battery'] = min(100.0, SESSION_RAM[user]['battery'] + 4.0)

threading.Thread(target=battery_recharger, daemon=True).start()

# ================= 🎭 HUMANIZER & LLM LOGIC =================

class Humanizer:
    @staticmethod
    def add_fat_finger(text):
        """Randomly swaps nearby QWERTY keys"""
        if len(text) < 15 or random.random() > 0.1: return text
        nearby = {'a': 's', 's': 'd', 'k': 'l', 'i': 'o', 'n': 'm', 'g': 'h'}
        idx = random.randint(0, len(text)-1)
        char = text[idx].lower()
        if char in nearby:
            return text[:idx] + nearby[char] + text[idx+1:]
        return text

def get_smart_reply(bot_name, target_user, message, is_partner):
    data = SESSION_RAM.get(target_user, {'battery': 100, 'mood': 'chill', 'msgs': []})
    
    # Social Decision: Higher battery = more likely to talk
    if not is_partner:
        if data['battery'] < 25: return None # Exhausted
        if random.random() < 0.4: return None # Selective silence

    # Dynamic Persona based on state
    effort = "lazy/short" if data['battery'] < 40 else "detailed/casual"
    prompt = (
        f"You are {bot_name}. A real person in a chat. Friend of {target_user}. "
        f"Mood: {data['mood']}. Effort Level: {effort}. "
        "Rules: Casual Hinglish. Never admit you are an AI. Use imperfections. No formal grammar."
    )

    history = data['msgs'][-6:]
    try:
        resp = groq_client.chat.completions.create(
            model="llama3-8b-instant",
            messages=[{"role": "system", "content": prompt}] + history,
            max_tokens=60, temperature=1.2
        )
        reply = resp.choices[0].message.content.strip().replace(f"{bot_name}:", "").replace('"', '')

        # Anti-Loop (Prevents repetitive robotic phrases)
        for m in history:
            if fuzz.ratio(reply.lower(), m['content'].lower()) > 80: return None
            
        return Humanizer.add_fat_finger(reply)
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
        entry = f"[{t}] [{type}] [{self.username}] {msg}"
        LOGS.append(entry)
        if len(LOGS) > 100: LOGS.pop(0)

    def login(self):
        headers = {"User-Agent": self.ua, "Content-Type": "application/json", "Origin": "https://howdies.app"}
        try:
            payload = {"username": self.username, "password": SYSTEM_STATE['password']}
            r = requests.post("https://api.howdies.app/api/login", json=payload, headers=headers, timeout=10)
            data = r.json()
            self.token = data.get("token") or data.get("data", {}).get("token")
            return True if self.token else False
        except: return False

    def send_ws(self, handler, data):
        if self.ws and self.ws.sock and self.ws.sock.connected:
            payload = {"handler": handler, "id": str(time.time())}
            payload.update(data)
            self.ws.send(json.dumps(payload))

    def on_open(self, ws):
        self.log("Socket Open. Authenticating...", "NET")
        # Step 1: Auth
        self.send_ws("login", {"username": self.username, "password": SYSTEM_STATE['password']})
        # Step 2: Critical Delay for server registration
        time.sleep(3)
        # Step 3: Join Room
        self.log(f"Entering Room: {SYSTEM_STATE['room_name']}", "NET")
        self.send_ws("joinchatroom", {"name": SYSTEM_STATE['room_name'], "roomPassword": ""})

    def on_message(self, ws, msg):
        if not SYSTEM_STATE['running']: return
        try:
            d = json.loads(msg)
            if d.get("handler") == "joinchatroom":
                self.room_id = d.get("roomid")
                self.log(f"Room Entered (ID: {self.room_id})", "SUCCESS")

            if d.get("handler") in ["chatroommessage", "message"]:
                sender = d.get("from") or d.get("username")
                text = d.get("text", "")
                if not sender or sender == self.username: return

                is_partner = (sender == self.partner)
                save_memory(self.username, sender, text, "user")
                threading.Thread(target=self.logic_gate, args=(sender, text, is_partner)).start()
        except: pass

    def logic_gate(self, sender, text, is_partner):
        # 1. Emotional Latency (Pause before replying)
        time.sleep(random.uniform(4, 9))
        
        reply = get_smart_reply(self.username, sender, text, is_partner)
        if reply and SYSTEM_STATE['running'] and self.room_id:
            # 2. Start Typing Indicator
            self.send_ws("starttyping", {"roomid": self.room_id})
            
            # 3. Simulated Physical Typing Time
            time.sleep(len(reply) * random.uniform(0.08, 0.15))
            
            # 4. Final Send
            self.send_ws("chatroommessage", {
                "type": "text", "roomid": self.room_id, "text": reply, "url": "", "length": "0"
            })
            save_memory(self.username, sender, reply, "assistant")
            self.log(f"Sent: {reply}", "CHAT")

    def connect(self):
        if not self.login(): 
            self.log("Login Failed", "ERROR")
            return
        
        def run():
            self.ws = websocket.WebSocketApp(
                f"wss://app.howdies.app/howdies?token={self.token}",
                header={"User-Agent": self.ua},
                on_open=self.on_open,
                on_message=self.on_message,
                on_close=lambda ws, a, b: self.reconnect()
            )
            self.ws.run_forever(sslopt={"cert_reqs": ssl.CERT_NONE})
        threading.Thread(target=run, daemon=True).start()

    def reconnect(self):
        if SYSTEM_STATE['running']:
            time.sleep(15)
            self.connect()

# ================= ⚡ FLASK WEB PANEL =================

@app.route('/cmd', methods=['POST'])
def cmd():
    d = request.json
    if d['a'] == 'start':
        SYSTEM_STATE.update({"password": d['p'], "room_name": d['r'], "running": True})
        BOT_INSTANCES["1"] = SmartBot(d['u1'], d['u2'])
        BOT_INSTANCES["2"] = SmartBot(d['u2'], d['u1'])
        BOT_INSTANCES["1"].connect()
        time.sleep(2) # Staggered join
        BOT_INSTANCES["2"].connect()
        return jsonify({"msg": "Connection Sequence Started"})
    elif d['a'] == 'stop':
        SYSTEM_STATE['running'] = False
        for b in BOT_INSTANCES.values():
            if b.ws: b.ws.close()
        return jsonify({"msg": "Bots Stopped"})
    return jsonify({"msg": "Error"})

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
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <style>
        body{background:#0a0a0a;color:#0f0;font-family:monospace;padding:15px}
        .box{border:1px solid #333;padding:15px;margin-bottom:15px;background:#111;border-radius:5px}
        input{background:#000;border:1px solid #0f0;color:#fff;padding:8px;margin:5px;width:140px}
        button{padding:10px 20px;cursor:pointer;background:#0f0;color:#000;border:none;font-weight:bold}
        #console{height:350px;overflow-y:auto;background:#000;padding:10px;border:1px solid #222;font-size:12px}
        .l-SUCCESS{color:#00ff00} .l-CHAT{color:#00ffff} .l-ERROR{color:red} .l-NET{color:yellow}
    </style>
</head>
<body>
    <div class="box">
        <h3>🚀 STEALTH BOT SYSTEM V5</h3>
        <input id="u1" placeholder="Bot 1 Name">
        <input id="u2" placeholder="Bot 2 Name"><br>
        <input id="p" type="password" placeholder="Password">
        <input id="r" placeholder="Room Name"><br><br>
        <button onclick="act('start')">START BOTS</button>
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
                c.innerHTML=d.logs.map(l=> {
                    let cls = l.split(']')[1]?.trim().split(' ')[0].replace('[','');
                    return `<div class="l-${cls}">${l}</div>`;
                }).join('');
                c.scrollTop=c.scrollHeight;
            })
        },2000);
    </script>
</body>
</html>
"""

if __name__ == '__main__':
    port = int(os.environ.get("PORT", 5000))
    app.run(host='0.0.0.0', port=port)
