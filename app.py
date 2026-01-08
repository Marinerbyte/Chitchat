import os, json, time, threading, random, websocket, ssl, requests
from flask import Flask, render_template_string, request, jsonify
from openai import OpenAI
from fuzzywuzzy import fuzz
from datetime import datetime

app = Flask(__name__)

# ================= 🔧 CONFIG =================
GROQ_API_KEY = os.environ.get("GROQ_API_KEY")
try:
    groq_client = OpenAI(base_url="https://api.groq.com/openai/v1", api_key=GROQ_API_KEY)
except: pass

SYSTEM_STATE = {"password": "", "room_name": "", "running": False}
LOGS = []
BOT_INSTANCES = {}
SESSION_RAM = {}

# ================= 🧠 BRAIN & RECHARGER =================

def save_memory(bot_name, user, message, role):
    if user not in SESSION_RAM:
        SESSION_RAM[user] = {'msgs': [], 'battery': 100.0, 'mood': 'chill'}
    data = SESSION_RAM[user]
    if role == "assistant": data['battery'] -= random.uniform(5, 10)
    data['msgs'].append({"role": role, "content": message})
    if len(data['msgs']) > 10: data['msgs'].pop(0)

def battery_recharger():
    while True:
        time.sleep(60)
        for u in list(SESSION_RAM.keys()):
            SESSION_RAM[u]['battery'] = min(100.0, SESSION_RAM[u]['battery'] + 5.0)

threading.Thread(target=battery_recharger, daemon=True).start()

# ================= 🎭 SMART REPLY LOGIC =================

def get_smart_reply(bot_name, target_user, message, is_partner):
    data = SESSION_RAM.get(target_user, {'battery': 100, 'mood': 'chill', 'msgs': []})
    
    # Partner ke liye reply chance 95% (Dono bots ek dusre ke partner hain)
    reply_chance = 0.95 if is_partner else 0.4
    if random.random() > reply_chance: return None

    prompt = (
        f"You are {bot_name}. Talking to your best friend {target_user}. "
        "Casual Hinglish, short messages, use slang like 'bro', 'yaar', 'sahi h'. "
        "Don't act like a bot. If you're bored, change the topic."
    )

    try:
        resp = groq_client.chat.completions.create(
            model="llama3-8b-instant",
            messages=[{"role": "system", "content": prompt}] + data['msgs'][-6:],
            max_tokens=50, temperature=1.2
        )
        reply = resp.choices[0].message.content.strip().replace(f"{bot_name}:", "").replace('"', '')
        return reply if len(reply) > 1 else None
    except: return "Aur bata?"

# ================= 🤖 SMART BOT CLASS =================

class SmartBot:
    def __init__(self, username, partner_name):
        self.username, self.partner, self.token, self.ws, self.room_id = username, partner_name, None, None, None
        self.ua = "Mozilla/5.0 (Linux; Android 14) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Mobile Safari/537.36"

    def log(self, msg, type="INFO"):
        LOGS.append(f"[{datetime.now().strftime('%H:%M:%S')}] [{type}] [{self.username}] {msg}")

    def login(self):
        try:
            r = requests.post("https://api.howdies.app/api/login", 
                json={"username": self.username, "password": SYSTEM_STATE['password']}, 
                headers={"User-Agent": self.ua}, timeout=10)
            self.token = r.json().get("token") or r.json().get("data", {}).get("token")
            return True if self.token else False
        except: return False

    def on_open(self, ws):
        self.log("Socket Open", "NET")
        ws.send(json.dumps({"handler": "login", "username": self.username, "password": SYSTEM_STATE['password']}))
        time.sleep(3)
        ws.send(json.dumps({"handler": "joinchatroom", "name": SYSTEM_STATE['room_name'], "roomPassword": ""}))

    def on_message(self, ws, msg):
        if not SYSTEM_STATE['running']: return
        try:
            d = json.loads(msg)
            if d.get("handler") == "joinchatroom": 
                self.room_id = d.get("roomid")
                self.log(f"In Room: {self.room_id}", "SUCCESS")
                # ICEBREAKER: Sirf pehla bot conversation start karega
                if "1" in [k for k, v in BOT_INSTANCES.items() if v == self]:
                    threading.Thread(target=self.kickstart).start()

            if d.get("handler") in ["chatroommessage", "message"]:
                sender, text = d.get("from") or d.get("username"), d.get("text", "")
                if not sender or sender == self.username: return
                
                is_partner = (sender == self.partner)
                save_memory(self.username, sender, text, "user")
                threading.Thread(target=self.process_reply, args=(sender, text, is_partner)).start()
        except: pass

    def kickstart(self):
        """Room join karte hi pehla message bhejna"""
        time.sleep(10)
        if self.room_id and SYSTEM_STATE['running']:
            msg = random.choice([f"Aur @{self.partner} kya scene?", "Bada sannata hai yahan..", "Koi hai?"])
            self.send_msg(msg)

    def process_reply(self, sender, text, is_partner):
        time.sleep(random.uniform(4, 8)) # Thinking time
        reply = get_smart_reply(self.username, sender, text, is_partner)
        if reply and SYSTEM_STATE['running']:
            # Typing signal
            ws_msg = {"handler": "starttyping", "roomid": self.room_id}
            self.ws.send(json.dumps(ws_msg))
            time.sleep(len(reply) * 0.1) # Typing speed
            self.send_msg(reply)

    def send_msg(self, text):
        if self.ws and self.room_id:
            payload = {"handler": "chatroommessage", "type": "text", "roomid": self.room_id, "text": text}
            self.ws.send(json.dumps(payload))
            save_memory(self.username, self.partner, text, "assistant")
            self.log(f"Sent: {text}", "CHAT")

    def connect(self):
        if not self.login(): return
        def run():
            self.ws = websocket.WebSocketApp(f"wss://app.howdies.app/howdies?token={self.token}",
                header={"User-Agent": self.ua}, on_open=self.on_open, on_message=self.on_message)
            self.ws.run_forever(sslopt={"cert_reqs": ssl.CERT_NONE})
        threading.Thread(target=run, daemon=True).start()

# ================= ⚡ FLASK =================

@app.route('/cmd', methods=['POST'])
def cmd():
    d = request.json
    if d['a'] == 'start':
        SYSTEM_STATE.update({"password": d['p'], "room_name": d['r'], "running": True})
        BOT_INSTANCES["1"] = SmartBot(d['u1'], d['u2'])
        BOT_INSTANCES["2"] = SmartBot(d['u2'], d['u1'])
        BOT_INSTANCES["1"].connect()
        time.sleep(5)
        BOT_INSTANCES["2"].connect()
        return jsonify({"msg": "Bots launching..."})
    elif d['a'] == 'stop':
        SYSTEM_STATE['running'] = False
        return jsonify({"msg": "Stopped"})
    return jsonify({"msg": "Error"})

@app.route('/logs')
def get_logs(): return jsonify({"logs": LOGS[-20:]})

@app.route('/')
def index():
    return render_template_string("""
    <body style="background:#000;color:#0f0;font-family:monospace;padding:20px">
        <h3>🚀 Bot Icebreaker Active</h3>
        <input id="u1" placeholder="User 1"> <input id="u2" placeholder="User 2">
        <input id="p" type="password" placeholder="Pass"> <input id="r" placeholder="Room">
        <button onclick="send('start')">START</button>
        <div id="logs" style="margin-top:20px;border:1px solid #333;padding:10px;height:300px;overflow:auto"></div>
        <script>
            function send(a){
                fetch('/cmd',{method:'POST',headers:{'Content-Type':'application/json'},
                body:JSON.stringify({a:a,u1:document.getElementById('u1').value,u2:document.getElementById('u2').value,p:document.getElementById('p').value,r:document.getElementById('r').value})})
            }
            setInterval(()=>{
                fetch('/logs').then(r=>r.json()).then(d=>{
                    document.getElementById('logs').innerHTML = d.logs.join('<br>');
                })
            },2000);
        </script>
    </body>
    """)

if __name__ == '__main__':
    port = int(os.environ.get("PORT", 5000))
    app.run(host='0.0.0.0', port=port)
