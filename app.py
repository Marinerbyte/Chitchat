import os
import json
import time
import threading
import random
import websocket
import ssl
import requests
import psycopg2
import textdistance
import emoji
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
except: pass

SYSTEM_STATE = {
    "password": "", "room_name": "", "running": False,
    "topics": ["latest movies", "cricket", "bangalore traffic", "street food", "gym", "tech", "memes"],
    "current_topic": "general"
}
LOGS = []

# 📱 STEALTH MODE: Real Device Fingerprints (Bot na lagne ke liye)
REAL_DEVICES = [
    "Mozilla/5.0 (Linux; Android 14; SM-S918B) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.6099.144 Mobile Safari/537.36",
    "Mozilla/5.0 (iPhone; CPU iPhone OS 17_4 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.4 Mobile/15E148 Safari/604.1",
    "Mozilla/5.0 (Linux; Android 13; Pixel 8 Pro) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.6167.101 Mobile Safari/537.36"
]

# ================= 🧠 HYBRID MEMORY MANAGER =================
SESSION_RAM = {}

def init_db():
    if not NEON_DB_URL: return
    try:
        conn = psycopg2.connect(NEON_DB_URL)
        cur = conn.cursor()
        cur.execute("""
            CREATE TABLE IF NOT EXISTS chat_history (
                id SERIAL PRIMARY KEY,
                bot_name TEXT, user_name TEXT, message TEXT, role TEXT,
                timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
        """)
        conn.commit()
        conn.close()
        print("✅ DB Connected")
    except Exception as e: print(f"❌ DB Error: {e}")

threading.Thread(target=init_db).start()

def save_memory(bot_name, user, message, role):
    curr_time = time.time()
    
    # Init RAM
    if user not in SESSION_RAM:
        SESSION_RAM[user] = {'msgs': [], 'last_active': curr_time, 'is_vip': False}
    
    data = SESSION_RAM[user]
    data['last_active'] = curr_time # Update sticky timer
    
    # CASE 1: VIP User (Serious) -> Direct DB
    if data['is_vip']:
        threading.Thread(target=db_insert, args=(bot_name, user, message, role)).start()
        return

    # CASE 2: Casual User -> RAM
    data['msgs'].append({"role": role, "content": message})
    
    # Logic: 5 message cross hote hi DB me shift
    if len(data['msgs']) > 5:
        log_sys(f"🚀 Promoting {user} to VIP Memory.", "MEMORY")
        for m in data['msgs']:
            db_insert(bot_name, user, m['content'], m['role'])
        data['is_vip'] = True
        data['msgs'] = [] 

def db_insert(bot, user, msg, role):
    try:
        conn = psycopg2.connect(NEON_DB_URL)
        cur = conn.cursor()
        cur.execute("INSERT INTO chat_history (bot_name, user_name, message, role) VALUES (%s,%s,%s,%s)", (bot, user, msg, role))
        conn.commit()
        conn.close()
    except: pass

def get_history(user):
    """Fetch Context (RAM or DB)"""
    if user in SESSION_RAM:
        if SESSION_RAM[user]['is_vip']:
            return fetch_db(user)
        return [{"role": m["role"], "content": m["content"]} for m in SESSION_RAM[user]['msgs']]
    return []

def fetch_db(user):
    try:
        conn = psycopg2.connect(NEON_DB_URL)
        cur = conn.cursor()
        cur.execute("SELECT role, message FROM chat_history WHERE user_name=%s ORDER BY timestamp DESC LIMIT 15", (user,))
        rows = cur.fetchall()
        conn.close()
        return [{"role": ("assistant" if r[0]=="assistant" else "user"), "content": r[1]} for r in reversed(rows)]
    except: return []

# Garbage Collector (30 Mins inactive clean)
def cleaner():
    while True:
        time.sleep(60)
        now = time.time()
        to_del = [u for u, d in SESSION_RAM.items() if (now - d['last_active'] > 1800 and not d['is_vip'])]
        for u in to_del: del SESSION_RAM[u]
threading.Thread(target=cleaner, daemon=True).start()

# ================= 🛡️ HUMANIZER & SAFETY ENGINE =================

class Humanizer:
    @staticmethod
    def check_safety(reply, history):
        """
        LIBRARY USE: FuzzyWuzzy & TextDistance
        Kaam: Check karta hai ki bot repeat to nahi kar raha.
        """
        if not reply or len(reply) < 2: return False
        
        for msg in history[-8:]:
            past_text = msg['content']
            # Fuzzy Ratio > 80% matlab same baat repeat ho rahi hai
            if fuzz.ratio(reply.lower(), past_text.lower()) > 80:
                log_sys(f"⚠️ Anti-Loop Triggered: '{reply}'", "SAFETY")
                return False
        return True

    @staticmethod
    def polish_emoji(text):
        """
        LIBRARY USE: Emoji
        Kaam: Agar text me emoji nahi hai, to mood ke hisab se daalta hai.
        """
        if emoji.emoji_count(text) > 0: return text
        
        t = text.lower()
        emo = "😅"
        if any(x in t for x in ['lol', 'haha', 'funny', 'mast']): emo = random.choice(['😂', '🤣', '🔥'])
        elif any(x in t for x in ['bhai', 'bro', 'yaar', 'sahi']): emo = random.choice(['😎', '🤙', '🤝'])
        elif any(x in t for x in ['love', 'dil', 'badhiya']): emo = random.choice(['❤️', '😍'])
        elif any(x in t for x in ['sad', 'bura', 'bekar', 'gussa']): emo = random.choice(['🥲', '💀', '😡'])
        
        return f"{text} {emo}"

    @staticmethod
    def add_typo(text):
        """
        Kaam: Jaan-boojh ke galti karna taaki insaan lage.
        """
        # 5% Chance: Swap chars (e.g. 'kay' instead of 'kya')
        if random.random() < 0.05 and len(text) > 6:
            idx = random.randint(0, len(text)-2)
            return text[:idx] + text[idx+1] + text[idx] + text[idx+2:]
        
        # Slang Shortcuts
        shortcuts = {"nahi": "ni", "hai": "h", "kya": "ky", "theek": "thik", "bhai": "bro"}
        words = text.split()
        return " ".join([shortcuts.get(w.lower(), w) if random.random() < 0.2 else w for w in words])

    @staticmethod
    def burst_split(text):
        """
        Kaam: Lambe message ko todna (Double Texting).
        """
        if len(text) > 50 and random.random() < 0.4:
            for sep in [',', ' aur ', ' but ', ' par ', ' lekin ']:
                if sep in text:
                    parts = text.split(sep, 1)
                    return [parts[0].strip(), (sep.strip() + " " + parts[1]).strip()]
        return [text]

def get_smart_reply(bot_name, target_user, message, is_partner):
    history = get_history(target_user)
    
    # Context System Prompt
    role = "Best friend" if is_partner else "Online friend"
    sys_p = f"Act as {bot_name}. {role} of {target_user}. Casual Hinglish. No formal AI language."
    
    msgs = [{"role": "system", "content": sys_p}]
    msgs.extend(history)
    if not history or history[-1]['content'] != message:
        msgs.append({"role": "user", "content": message})

    # Retry Mechanism (3 Tries)
    for _ in range(3):
        try:
            resp = groq_client.chat.completions.create(
                model="llama3-8b-instant", messages=msgs, max_tokens=70, temperature=1.2
            )
            raw = resp.choices[0].message.content.strip().replace(f"{bot_name}:", "").replace('"', '')
            
            # 1. Safety Check (FuzzyWuzzy)
            if not Humanizer.check_safety(raw, history): continue
            
            # 2. Typos (Humanize)
            humanized = Humanizer.add_typo(raw)
            
            # 3. Emojis (Polish)
            final = Humanizer.polish_emoji(humanized)
            
            return final

        except Exception as e: time.sleep(1)

    return random.choice(["Aur batao?", "Hmm..", "Sahi hai", "Achha suno.."])

# ================= 🤖 SMART BOT CLASS =================

class SmartBot:
    def __init__(self, username, partner_name):
        self.username = username
        self.partner = partner_name
        self.token = None
        self.ws = None
        self.room_id = None
        # STEALTH MODE: Pick Random Real Device ID
        self.ua = random.choice(REAL_DEVICES)

    def log(self, msg, type="INFO"):
        t = datetime.now().strftime("%H:%M:%S")
        entry = f"[{t}] [{type}] [{self.username}] {msg}"
        print(entry)
        LOGS.append(entry)
        if len(LOGS) > 300: LOGS.pop(0)

    def login(self):
        # STEALTH: Using self.ua (Real Device) in headers
        headers = {"User-Agent": self.ua, "Content-Type": "application/json", "Origin": "https://howdies.app"}
        try:
            r = requests.post("https://api.howdies.app/api/login", 
                json={"username": self.username, "password": SYSTEM_STATE['password']}, 
                headers=headers, timeout=15)
            if r.status_code == 200:
                self.token = r.json().get("token") or r.json().get("data", {}).get("token")
                return True
        except: pass
        return False

    def connect(self):
        if not self.token and not self.login(): return
        
        # STEALTH: Headers in WebSocket too
        self.ws = websocket.WebSocketApp(
            f"wss://app.howdies.app/howdies?token={self.token}",
            header={"User-Agent": self.ua, "Origin": "https://howdies.app"},
            on_open=self.on_open, on_message=self.on_message, on_error=self.on_error, on_close=self.on_close
        )
        threading.Thread(target=self.ws.run_forever, kwargs={"sslopt": {"cert_reqs": ssl.CERT_NONE}}, daemon=True).start()

    def on_open(self, ws):
        self.log("Connected (Stealth Mode Active)", "NET")
        ws.send(json.dumps({"handler": "login", "username": self.username, "password": SYSTEM_STATE['password']}))
        time.sleep(1)
        ws.send(json.dumps({"handler": "joinchatroom", "id": str(time.time()), "name": SYSTEM_STATE['room_name'], "roomPassword": ""}))
        threading.Thread(target=self.heartbeat, daemon=True).start()

    def on_message(self, ws, msg):
        if not SYSTEM_STATE['running']: return
        try:
            d = json.loads(msg)
            if d.get("handler") == "joinchatroom": self.room_id = d.get("roomid")
            
            if d.get("handler") in ["chatroommessage", "message"]:
                sender = d.get("from") or d.get("username")
                text = d.get("text")
                if not sender or not text or sender == self.username: return

                is_partner = (sender == self.partner)
                should_reply = False

                # === DECISION LOGIC (STICKY SESSION & CONTEXT) ===
                if is_partner: 
                    should_reply = True
                
                elif self.username.lower() in text.lower(): 
                    should_reply = True
                
                # STICKY SESSION: Agar user ne pichle 60s me baat ki thi, to bina naam liye bhi reply karo
                elif sender in SESSION_RAM and (time.time() - SESSION_RAM[sender]['last_active'] < 60):
                    should_reply = True
                    log_sys(f"📎 Sticky Trigger for {sender}", "LOGIC")

                if should_reply:
                    save_memory(self.username, sender, text, "user")
                    threading.Thread(target=self.process_reply, args=(sender, text, is_partner)).start()
        except: pass

    def process_reply(self, target_user, text, is_partner):
        # Human Delay (Calculate based on text length)
        time.sleep(len(text)*0.04 + random.uniform(1.5, 3.5))
        if not SYSTEM_STATE['running']: return

        reply = get_smart_reply(self.username, target_user, text, is_partner)
        save_memory(self.username, target_user, reply, "assistant")

        msgs = Humanizer.burst_split(reply)
        for m in msgs:
            time.sleep(len(m) * 0.08) # Typing Speed
            self.log(f"Typing to {target_user}...", "TYPING")
            if self.ws and self.room_id:
                self.ws.send(json.dumps({
                    "handler": "chatroommessage", "id": str(time.time()),
                    "type": "text", "roomid": self.room_id, "text": m, "url": "", "length": "0"
                }))
                self.log(f"Replied: {m}", "CHAT")

    def on_error(self, ws, err): pass
    def on_close(self, ws, *args): 
        time.sleep(5)
        if SYSTEM_STATE['running']: self.connect()
    def heartbeat(self):
        while self.ws and self.ws.sock and self.ws.sock.connected:
            time.sleep(30)
            try: self.ws.send(json.dumps({"handler":"ping"}))
            except: break

# ================= 🎛️ CONTROL PANEL =================
BOT_INSTANCES = {}

def log_sys(msg, type="INFO"):
    LOGS.append(f"[{datetime.now().strftime('%H:%M:%S')}] [{type}] {msg}")

def start_system(u1, u2, pwd, room):
    SYSTEM_STATE.update({"password": pwd, "room_name": room, "running": True})
    BOT_INSTANCES["1"] = SmartBot(u1, u2)
    BOT_INSTANCES["2"] = SmartBot(u2, u1)
    BOT_INSTANCES["1"].connect()
    BOT_INSTANCES["2"].connect()
    threading.Thread(target=kickstart, daemon=True).start()

def kickstart():
    time.sleep(10)
    b = BOT_INSTANCES.get("1")
    if b and b.room_id and SYSTEM_STATE['running']:
        msg = f"Aur bhai {b.partner}, kya scene? 😎"
        b.ws.send(json.dumps({"handler":"chatroommessage","id":str(time.time()),"type":"text","roomid":b.room_id,"text":msg,"url":"","length":"0"}))
        save_memory(b.username, b.partner, msg, "assistant")

@app.route('/cmd', methods=['POST'])
def cmd():
    d = request.json
    if d['a'] == 'start': start_system(d['u1'], d['u2'], d['p'], d['r'])
    if d['a'] == 'stop':
        SYSTEM_STATE['running'] = False
        for b in BOT_INSTANCES.values(): 
            if b.ws: b.ws.close()
    return jsonify({"msg": "Done"})

@app.route('/logs')
def logs(): return jsonify({"logs": LOGS})

HTML = """
<!DOCTYPE html>
<html lang="en">
<head>
    <title>Master Bot</title>
    <style>
        body{background:#000;color:#0f0;font-family:monospace;padding:20px}
        .box{border:1px solid #444;padding:15px;background:#111;margin-bottom:10px}
        input{width:100%;padding:10px;background:#222;border:1px solid #555;color:#fff}
        button{width:48%;padding:10px;cursor:pointer;font-weight:bold}
        .start{background:darkgreen;color:#fff} .stop{background:darkred;color:#fff}
        #console{height:400px;overflow-y:auto;background:#050505;border:1px solid #333;padding:10px}
        .l-CHAT{color:cyan} .l-TYPING{color:magenta} .l-SAFETY{color:red} .l-MEMORY{color:yellow}
    </style>
</head>
<body>
    <div class="box">
        <h2>🔥 MASTER BOT (All Features Loaded)</h2>
        <div style="display:flex;gap:10px"><input id="u1" placeholder="User 1"><input id="u2" placeholder="User 2"></div><br>
        <div style="display:flex;gap:10px"><input id="p" type="password" placeholder="Pass"><input id="r" value="testroom"></div><br>
        <div style="display:flex;justify-content:space-between">
            <button class="start" onclick="act('start')">START</button>
            <button class="stop" onclick="act('stop')">STOP</button>
        </div>
    </div>
    <div class="box"><div id="console"></div></div>
    <script>
        function act(a){
            fetch('/cmd',{method:'POST',headers:{'Content-Type':'application/json'},
            body:JSON.stringify({a:a,u1:document.getElementById('u1').value,u2:document.getElementById('u2').value,p:document.getElementById('p').value,r:document.getElementById('r').value})})
            .then(r=>r.json()).then(d=>alert(d.msg));
        }
        setInterval(()=>{
            fetch('/logs').then(r=>r.json()).then(d=>{
                const c=document.getElementById('console');
                const s=c.scrollTop===c.scrollHeight-c.clientHeight;
                c.innerHTML=d.logs.map(l=>{
                    let cl='white';
                    if(l.includes('CHAT')) cl='l-CHAT';
                    if(l.includes('TYPING')) cl='l-TYPING';
                    if(l.includes('SAFETY')) cl='l-SAFETY';
                    if(l.includes('MEMORY')) cl='l-MEMORY';
                    return `<div class="${cl}">${l}</div>`;
                }).join('');
                if(s) c.scrollTop=c.scrollHeight;
            })
        },1000);
    </script>
</body>
</html>
"""
@app.route('/')
def index(): return render_template_string(HTML)

if __name__ == '__main__':
    port = int(os.environ.get("PORT", 5000))
    app.run(host='0.0.0.0', port=port)
