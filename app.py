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

SYSTEM_STATE = {"password": "", "room_name": "", "running": False, "status": "Offline"}
LOGS = []
BOTS = {"1": None, "2": None}

# Professional Headers to bypass detection
BASE_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Linux; Android 10; K) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Mobile Safari/537.36",
    "Origin": "https://howdies.app",
    "Referer": "https://howdies.app/"
}

# ================= 🧠 AI BRAIN =================

def get_ai_reply(bot_name, user, msg):
    try:
        prompt = f"Act as {bot_name}. Friend of {user}. Short 1-line Hinglish reply. No formal AI talk."
        resp = groq_client.chat.completions.create(
            model="llama3-8b-instant",
            messages=[{"role": "system", "content": prompt}, {"role": "user", "content": msg}],
            max_tokens=40, temperature=1.1
        )
        return resp.choices[0].message.content.strip()
    except: return random.choice(["Hmm", "Aur bata?", "Sahi hai", "😂"])

# ================= 🤖 GHOST BOT ENGINE =================

class GhostBot:
    def __init__(self, name, partner):
        self.name = name
        self.partner = partner
        self.ws = None
        self.token = None
        self.active = False
        self.room_id = None

    def log(self, msg, tag="INFO"):
        t = datetime.now().strftime("%H:%M:%S")
        LOGS.append(f"[{t}] [{tag}] [{self.name}] {msg}")

    def login(self):
        try:
            self.log("Bypassing API Auth...", "AUTH")
            r = requests.post("https://api.howdies.app/api/login", 
                json={"username": self.name, "password": SYSTEM_STATE['password']}, 
                headers=BASE_HEADERS, timeout=15)
            
            if r.status_code == 403:
                self.log("IP Blocked by App (Render IP issue)", "CRITICAL")
                return False
            
            res = r.json()
            self.token = res.get("token") or res.get("data", {}).get("token")
            return True if self.token else False
        except Exception as e:
            self.log(f"Login Error: {str(e)}", "ERROR")
            return False

    def on_open(self, ws):
        self.log("Tunnel Open. Sending Credentials...", "NET")
        # Step 1: Login Handler
        ws.send(json.dumps({"handler": "login", "username": self.name, "password": SYSTEM_STATE['password']}))
        
        # Step 2: Random Delay for Room Join (Real user behavior)
        def join():
            time.sleep(random.uniform(5, 10))
            if self.active:
                self.log(f"Requesting Room: {SYSTEM_STATE['room_name']}", "NET")
                ws.send(json.dumps({"handler": "joinchatroom", "name": SYSTEM_STATE['room_name'], "roomPassword": ""}))
        threading.Thread(target=join, daemon=True).start()

    def on_message(self, ws, msg):
        try:
            d = json.loads(msg)
            if d.get("handler") == "joinchatroom" and d.get("roomid"):
                self.room_id = d.get("roomid")
                self.log("Vibe Check Passed. Room Active.", "LIVE")
            
            if d.get("handler") in ["chatroommessage", "message"]:
                sender, text = d.get("from") or d.get("username"), d.get("text", "")
                if sender and sender != self.name:
                    if sender == self.partner or self.name.lower() in text.lower():
                        threading.Thread(target=self.reply_logic, args=(sender, text)).start()
        except: pass

    def reply_logic(self, sender, text):
        time.sleep(random.uniform(4, 8))
        reply = get_ai_reply(self.name, sender, text)
        if self.ws and self.room_id:
            try:
                self.ws.send(json.dumps({"handler": "starttyping", "roomid": self.room_id}))
                time.sleep(len(reply) * 0.1)
                self.ws.send(json.dumps({"handler": "chatroommessage", "type": "text", "roomid": self.room_id, "text": reply}))
                self.log(f"Replied: {reply}", "CHAT")
            except: pass

    def connect(self):
        if not self.login(): return
        self.active = True
        
        def run():
            # WS Headers are critical for Howdies detection
            headers = [f"User-Agent: {BASE_HEADERS['User-Agent']}", f"Origin: {BASE_HEADERS['Origin']}"]
            self.ws = websocket.WebSocketApp(
                f"wss://app.howdies.app/howdies?token={self.token}",
                header=headers,
                on_open=self.on_open,
                on_message=self.on_message,
                on_error=lambda ws, e: self.log(f"Socket Loss: {e}", "NET"),
                on_close=lambda ws, a, b: self.reconnect()
            )
            self.ws.run_forever(sslopt={"cert_reqs": ssl.CERT_NONE}, ping_interval=30, ping_timeout=10)
        
        threading.Thread(target=run, daemon=True).start()

    def reconnect(self):
        if SYSTEM_STATE['running'] and self.active:
            self.log("Ghosting failed. Retrying Tunnel...", "RETRY")
            time.sleep(random.uniform(10, 20))
            self.connect()

    def stop(self):
        self.active = False
        if self.ws: self.ws.close()

# ================= ⚡ CONTROL PANEL =================

@app.route('/cmd', methods=['POST'])
def cmd():
    data = request.json
    a = data.get('a')
    if a == 'start':
        SYSTEM_STATE.update({"password": data['p'], "room_name": data['r'], "running": True, "status": "Connecting..."})
        BOTS["1"] = GhostBot(data['u1'], data['u2'])
        BOTS["2"] = GhostBot(data['u2'], data['u1'])
        BOTS["1"].connect()
        threading.Timer(12, BOTS["2"].connect).start()
        return jsonify({"s": "ok"})
    if a == 'logout':
        SYSTEM_STATE['running'] = False
        SYSTEM_STATE['status'] = "Offline"
        if BOTS["1"]: BOTS["1"].stop()
        if BOTS["2"]: BOTS["2"].stop()
        LOGS.clear()
        return jsonify({"s": "wiped"})
    return jsonify({"s": "err"})

@app.route('/logs')
def get_logs():
    s = SYSTEM_STATE['status']
    if SYSTEM_STATE['running']:
        s = "Connected" if (BOTS["1"] and BOTS["1"].room_id) else "Handshaking..."
    return jsonify({"logs": LOGS[-25:], "status": s})

@app.route('/')
def index():
    return render_template_string(UI)

# ================= 🎨 UI =================

UI = """
<!DOCTYPE html>
<html>
<head>
    <title>GHOST BOT V8</title>
    <style>
        body { background: #000; color: #0f0; font-family: monospace; padding: 20px; }
        .card { border: 1px solid #222; padding: 20px; background: #050505; margin-bottom: 20px; }
        .status { font-weight: bold; color: yellow; margin-bottom: 10px; }
        input { background: #111; border: 1px solid #333; color: #fff; padding: 10px; margin: 5px 0; width: 100%; box-sizing: border-box; }
        button { padding: 15px; width: 48%; cursor: pointer; border: none; font-weight: bold; }
        .start { background: #0f0; color: #000; }
        .wipe { background: #f00; color: #fff; }
        #log { height: 350px; overflow: auto; border: 1px solid #111; padding: 10px; font-size: 12px; }
        .tag-LIVE { color: #0f0; border: 1px solid #0f0; padding: 1px 3px; }
        .tag-CHAT { color: cyan; } .tag-CRITICAL { color: white; background: red; }
    </style>
</head>
<body>
    <div class="card">
        <div class="status">System Status: <span id="st">Offline</span></div>
        <input id="u1" placeholder="Bot 1 Name">
        <input id="u2" placeholder="Bot 2 Name">
        <input id="p" type="password" placeholder="Password">
        <input id="r" placeholder="Room Name">
        <div style="display: flex; justify-content: space-between; margin-top:10px;">
            <button class="start" onclick="act('start')">GHOST CONNECT</button>
            <button class="wipe" onclick="act('logout')">LOGOUT & WIPE</button>
        </div>
    </div>
    <div id="log" class="card"></div>
    <script>
        function act(a){
            fetch('/cmd',{method:'POST',headers:{'Content-Type':'application/json'},
            body:JSON.stringify({a:a,u1:document.getElementById('u1').value,u2:document.getElementById('u2').value,p:document.getElementById('p').value,r:document.getElementById('r').value})});
        }
        setInterval(()=>{
            fetch('/logs').then(r=>r.json()).then(d=>{
                document.getElementById('st').innerText = d.status;
                document.getElementById('log').innerHTML = d.logs.map(l => {
                    let tag = l.split(']')[1]?.trim().split(' ')[0].replace('[','');
                    return `<div style="margin-bottom:4px"><span class="tag-${tag}">${tag}</span> ${l.split(']')[3] || l}</div>`;
                }).join('');
                document.getElementById('log').scrollTop = 99999;
            })
        }, 1500);
    </script>
</body>
</html>
"""

if __name__ == '__main__':
    port = int(os.environ.get("PORT", 5000))
    app.run(host='0.0.0.0', port=port)
