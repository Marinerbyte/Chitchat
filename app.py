import os, json, time, threading, random, websocket, ssl, requests
from flask import Flask, render_template_string, request, jsonify
from openai import OpenAI
from datetime import datetime

app = Flask(__name__)

# ================= 🔧 CONFIG =================
GROQ_API_KEY = os.environ.get("GROQ_API_KEY")
try:
    groq_client = OpenAI(base_url="https://api.groq.com/openai/v1", api_key=GROQ_API_KEY)
except: pass

# Global States
BRAIN = {"lock": threading.Lock(), "last_msg_time": 0, "room_id": None}
SYSTEM_STATE = {"password": "", "room_name": "", "running": False, "status": "Offline"}
LOGS = []
BOTS = {"1": None, "2": None}

USER_AGENTS = [
    "Mozilla/5.0 (Linux; Android 14; SM-S918B) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.6099.144 Mobile Safari/537.36",
    "Mozilla/5.0 (iPhone; CPU iPhone OS 17_4 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.4 Mobile/15E148 Safari/604.1"
]

# ================= 🧠 AI BRAIN =================

def get_ai_reply(bot_name, user, msg):
    try:
        prompt = f"Act as {bot_name}. Reply to {user} in 1 short Hinglish line. Be casual, use emojis like 😂, 😎. No bot talk."
        resp = groq_client.chat.completions.create(
            model="llama3-8b-instant",
            messages=[{"role": "system", "content": prompt}, {"role": "user", "content": msg}],
            max_tokens=40, temperature=1.1
        )
        return resp.choices[0].message.content.strip()
    except: return random.choice(["Hmm", "Sahi h", "Theek h", "😂"])

# ================= 🤖 MIRROR BOT ENGINE =================

class MirrorBot:
    def __init__(self, name, partner):
        self.name = name
        self.partner = partner
        self.ws = None
        self.token = None
        self.ua = random.choice(USER_AGENTS)
        self.active = False

    def log(self, msg, tag="INFO"):
        t = datetime.now().strftime("%H:%M:%S")
        LOGS.append(f"[{t}] [{tag}] [{self.name}] {msg}")

    def login(self):
        try:
            r = requests.post("https://api.howdies.app/api/login", 
                json={"username": self.name, "password": SYSTEM_STATE['password']}, 
                headers={"User-Agent": self.ua}, timeout=10)
            data = r.json()
            self.token = data.get("token") or data.get("data", {}).get("token")
            return True if self.token else False
        except: return False

    def on_message(self, ws, msg):
        try:
            d = json.loads(msg)
            if d.get("handler") == "joinchatroom":
                BRAIN["room_id"] = d.get("roomid")
                self.active = True
                self.log("Joined Room", "LIVE")
            
            if d.get("handler") in ["chatroommessage", "message"]:
                sender, text = d.get("from") or d.get("username"), d.get("text", "")
                if sender and sender != self.name:
                    if sender == self.partner or self.name.lower() in text.lower():
                        threading.Thread(target=self.reply_logic, args=(sender, text)).start()
        except: pass

    def reply_logic(self, sender, text):
        time.sleep(random.uniform(3, 7))
        reply = get_ai_reply(self.name, sender, text)
        if self.ws and self.active:
            self.ws.send(json.dumps({"handler": "starttyping", "roomid": BRAIN["room_id"]}))
            time.sleep(len(reply) * 0.1)
            self.ws.send(json.dumps({"handler": "chatroommessage", "type": "text", "roomid": BRAIN["room_id"], "text": reply}))
            self.log(f"Replied: {reply}", "CHAT")

    def connect(self):
        if not self.login(): return self.log("Login Failed", "ERROR")
        
        def run():
            self.ws = websocket.WebSocketApp(
                f"wss://app.howdies.app/howdies?token={self.token}",
                header={"User-Agent": self.ua},
                on_open=lambda ws: (
                    ws.send(json.dumps({"handler": "login", "username": self.name, "password": SYSTEM_STATE['password']})),
                    time.sleep(4),
                    ws.send(json.dumps({"handler": "joinchatroom", "name": SYSTEM_STATE['room_name'], "roomPassword": ""}))
                ),
                on_message=self.on_message,
                on_close=lambda ws, a, b: self.reconnect()
            )
            self.ws.run_forever(sslopt={"cert_reqs": ssl.CERT_NONE}, ping_interval=40)
        
        threading.Thread(target=run, daemon=True).start()

    def reconnect(self):
        if SYSTEM_STATE['running']:
            self.active = False
            time.sleep(10)
            self.connect()

    def disconnect(self):
        self.active = False
        if self.ws: self.ws.close()

# ================= ⚡ FLASK CONTROL =================

@app.route('/cmd', methods=['POST'])
def cmd():
    data = request.json
    action = data.get('a')
    
    if action == 'start':
        SYSTEM_STATE.update({"password": data['p'], "room_name": data['r'], "running": True, "status": "Connecting..."})
        BOTS["1"] = MirrorBot(data['u1'], data['u2'])
        BOTS["2"] = MirrorBot(data['u2'], data['u1'])
        BOTS["1"].connect()
        threading.Timer(15, BOTS["2"].connect).start()
        return jsonify({"status": "Sequence Started"})

    if action == 'logout':
        SYSTEM_STATE['running'] = False
        SYSTEM_STATE['status'] = "Offline"
        if BOTS["1"]: BOTS["1"].disconnect()
        if BOTS["2"]: BOTS["2"].disconnect()
        LOGS.clear() # Wipe Terminal
        return jsonify({"status": "Logged Out & Wiped"})

    return jsonify({"status": "Error"})

@app.route('/logs')
def get_logs():
    if SYSTEM_STATE['running']:
        SYSTEM_STATE['status'] = "Active" if (BOTS["1"] and BOTS["1"].active) else "Connecting..."
    return jsonify({"logs": LOGS[-20:], "status": SYSTEM_STATE['status']})

@app.route('/')
def index():
    return render_template_string(HTML_DASHBOARD)

# ================= 🎨 MODERN UI =================

HTML_DASHBOARD = """
<!DOCTYPE html>
<html>
<head>
    <title>Aura-Link V7 Dashboard</title>
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <style>
        :root { --main: #00ff41; --bg: #050505; --card: #0f0f0f; }
        body { background: var(--bg); color: #fff; font-family: 'Segoe UI', sans-serif; margin: 0; padding: 20px; }
        .grid { max-width: 800px; margin: auto; }
        .card { background: var(--card); border: 1px solid #222; padding: 20px; border-radius: 8px; margin-bottom: 20px; }
        .status-bar { display: flex; justify-content: space-between; align-items: center; border-bottom: 2px solid var(--main); padding-bottom: 10px; }
        .dot { height: 10px; width: 10px; background: #555; border-radius: 50%; display: inline-block; margin-right: 5px; }
        .online .dot { background: var(--main); box-shadow: 0 0 10px var(--main); }
        input { background: #000; border: 1px solid #333; color: #fff; padding: 12px; border-radius: 4px; width: 100%; box-sizing: border-box; margin-top: 10px; }
        .btn-group { display: grid; grid-template-columns: 1fr 1fr; gap: 10px; margin-top: 20px; }
        button { padding: 15px; border: none; border-radius: 4px; font-weight: bold; cursor: pointer; transition: 0.3s; }
        .btn-start { background: var(--main); color: #000; }
        .btn-logout { background: #ff003c; color: #fff; }
        button:hover { opacity: 0.8; }
        #terminal { background: #000; border: 1px solid #111; height: 300px; overflow-y: auto; padding: 15px; font-family: 'Courier New', monospace; font-size: 13px; color: var(--main); border-radius: 4px; }
        .tag-CHAT { color: #00f2ff; } .tag-ERROR { color: #ff003c; } .tag-LIVE { color: var(--main); font-weight: bold; }
    </style>
</head>
<body>
    <div class="grid">
        <div class="card status-bar" id="status-card">
            <h2 style="margin:0; font-size: 18px;">AURA-LINK V7</h2>
            <div id="stat-text"><span class="dot"></span> Offline</div>
        </div>

        <div class="card">
            <div style="display: grid; grid-template-columns: 1fr 1fr; gap: 10px;">
                <input id="u1" placeholder="Bot 1 Username">
                <input id="u2" placeholder="Bot 2 Username">
            </div>
            <input id="p" type="password" placeholder="Account Password">
            <input id="r" placeholder="Room Name">
            
            <div class="btn-group">
                <button class="btn-start" onclick="run('start')">START ENGINE</button>
                <button class="btn-logout" onclick="run('logout')">LOGOUT & WIPE</button>
            </div>
        </div>

        <div id="terminal"></div>
    </div>

    <script>
        function run(a){
            const data = {
                a: a, 
                u1: document.getElementById('u1').value,
                u2: document.getElementById('u2').value,
                p: document.getElementById('p').value,
                r: document.getElementById('r').value
            };
            fetch('/cmd', {
                method: 'POST', 
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify(data)
            });
            if(a === 'logout') {
                document.getElementById('terminal').innerHTML = '';
            }
        }

        setInterval(() => {
            fetch('/logs').then(r => r.json()).then(d => {
                const term = document.getElementById('terminal');
                const stat = document.getElementById('status-card');
                const statText = document.getElementById('stat-text');

                // Update Status UI
                if(d.status === "Active") {
                    stat.classList.add('online');
                    statText.innerHTML = '<span class="dot"></span> Online';
                } else {
                    stat.classList.remove('online');
                    statText.innerHTML = '<span class="dot"></span> ' + d.status;
                }

                // Update Terminal
                term.innerHTML = d.logs.map(l => {
                    const tag = l.split(']')[1]?.trim().split(' ')[0].replace('[','');
                    return `<div class="tag-${tag}">${l}</div>`;
                }).join('');
                term.scrollTop = term.scrollHeight;
            });
        }, 2000);
    </script>
</body>
</html>
"""

if __name__ == '__main__':
    port = int(os.environ.get("PORT", 5000))
    app.run(host='0.0.0.0', port=port)
