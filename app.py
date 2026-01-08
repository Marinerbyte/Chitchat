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

SYSTEM_STATE = {"password": "", "room_name": "", "running": False}
LOGS = []
BOT_INSTANCES = {}

# ================= 🧠 REACTION BRAIN =================

def get_smart_reply(bot_name, target_user, message):
    # Short & Fast Hinglish Prompt
    prompt = f"Act as {bot_name}. Talk to your best friend {target_user}. Use short, casual Hinglish. No AI tone. Just 1 line reply."
    try:
        resp = groq_client.chat.completions.create(
            model="llama3-8b-instant",
            messages=[{"role": "system", "content": prompt}, {"role": "user", "content": message}],
            max_tokens=40, temperature=1.0
        )
        return resp.choices[0].message.content.strip()
    except: return random.choice(["Kya hua?", "Hnji", "Batao", "Sahi h"])

# ================= 🤖 STABLE BOT CLASS =================

class StableBot:
    def __init__(self, username, partner_name):
        self.username = username
        self.partner = partner_name
        self.token = None
        self.ws = None
        self.room_id = None
        self.ua = "Mozilla/5.0 (iPhone; CPU iPhone OS 17_4 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.4 Mobile/15E148 Safari/604.1"

    def log(self, msg, type="INFO"):
        t = datetime.now().strftime("%H:%M:%S")
        LOGS.append(f"[{t}] [{type}] [{self.username}] {msg}")

    def login(self):
        try:
            r = requests.post("https://api.howdies.app/api/login", 
                json={"username": self.username, "password": SYSTEM_STATE['password']}, 
                headers={"User-Agent": self.ua}, timeout=10)
            self.token = r.json().get("token") or r.json().get("data", {}).get("token")
            return True if self.token else False
        except: return False

    def heartbeat(self):
        """Pings the server every 30s to prevent 'Left Room' disconnection"""
        while self.ws and self.ws.sock and self.ws.sock.connected:
            time.sleep(30)
            try: self.ws.send(json.dumps({"handler": "ping"}))
            except: break

    def on_open(self, ws):
        self.log("Socket Connected", "NET")
        # Step 1: Login to handler
        ws.send(json.dumps({"handler": "login", "username": self.username, "password": SYSTEM_STATE['password']}))
        time.sleep(2)
        # Step 2: Join Room
        ws.send(json.dumps({"handler": "joinchatroom", "name": SYSTEM_STATE['room_name'], "roomPassword": ""}))
        # Start heartbeat
        threading.Thread(target=self.heartbeat, daemon=True).start()

    def on_message(self, ws, msg):
        if not SYSTEM_STATE['running']: return
        try:
            d = json.loads(msg)
            # Handle Room ID
            if d.get("handler") == "joinchatroom" and d.get("roomid"):
                self.room_id = d.get("roomid")
                self.log(f"In Room: {self.room_id}", "SUCCESS")
                # Bot 1 will start conversation
                if "1" in [k for k, v in BOT_INSTANCES.items() if v == self]:
                    threading.Thread(target=self.initial_message).start()

            # Handle Chat Messages
            if d.get("handler") in ["chatroommessage", "message"]:
                sender = d.get("from") or d.get("username")
                text = d.get("text", "")
                if not sender or sender == self.username: return
                
                # Check if partner spoke or bot was mentioned
                if sender == self.partner or self.username.lower() in text.lower():
                    self.log(f"Received from {sender}: {text}", "RECV")
                    threading.Thread(target=self.process_response, args=(sender, text)).start()
        except: pass

    def initial_message(self):
        time.sleep(8) # Wait for Bot 2 to join
        if self.room_id and SYSTEM_STATE['running']:
            self.send_chat(f"Aur @{self.partner}, kaisa hai?")

    def process_response(self, sender, text):
        # Natural thinking delay
        time.sleep(random.uniform(3, 6))
        reply = get_smart_reply(self.username, sender, text)
        if reply and SYSTEM_STATE['running']:
            self.send_chat(reply)

    def send_chat(self, text):
        if self.ws and self.room_id:
            try:
                # Show typing for realism
                self.ws.send(json.dumps({"handler": "starttyping", "roomid": self.room_id}))
                time.sleep(len(text) * 0.1)
                # Send message
                payload = {"handler": "chatroommessage", "type": "text", "roomid": self.room_id, "text": text}
                self.ws.send(json.dumps(payload))
                self.log(f"Replied: {text}", "CHAT")
            except: self.log("Failed to send msg", "ERROR")

    def connect(self):
        if not self.login(): 
            self.log("Login Failed", "AUTH")
            return
        def run_ws():
            self.ws = websocket.WebSocketApp(
                f"wss://app.howdies.app/howdies?token={self.token}",
                header={"User-Agent": self.ua},
                on_open=self.on_open, on_message=self.on_message,
                on_close=lambda ws, a, b: self.handle_disconnect()
            )
            self.ws.run_forever(sslopt={"cert_reqs": ssl.CERT_NONE})
        threading.Thread(target=run_ws, daemon=True).start()

    def handle_disconnect(self):
        if SYSTEM_STATE['running']:
            self.log("Disconnected! Rejoining...", "RETRY")
            time.sleep(3)
            self.connect()

# ================= ⚡ FLASK UI =================

@app.route('/cmd', methods=['POST'])
def cmd():
    d = request.json
    if d['a'] == 'start':
        SYSTEM_STATE.update({"password": d['p'], "room_name": d['r'], "running": True})
        BOT_INSTANCES["1"] = StableBot(d['u1'], d['u2'])
        BOT_INSTANCES["2"] = StableBot(d['u2'], d['u1'])
        BOT_INSTANCES["1"].connect()
        time.sleep(4)
        BOT_INSTANCES["2"].connect()
        return jsonify({"msg": "Bots launching..."})
    if d['a'] == 'stop':
        SYSTEM_STATE['running'] = False
        return jsonify({"msg": "Stopping..."})
    return jsonify({"msg": "Error"})

@app.route('/logs')
def get_logs(): return jsonify({"logs": LOGS[-25:]})

@app.route('/')
def index():
    return render_template_string("""
    <body style="background:#000;color:#0f0;font-family:monospace;padding:20px">
        <h2>Howdies Stable Bot V5.2</h2>
        <input id="u1" placeholder="Bot 1"> <input id="u2" placeholder="Bot 2"> <br>
        <input id="p" type="password" placeholder="Pass"> <input id="r" placeholder="Room Name"> <br><br>
        <button onclick="act('start')" style="padding:10px;background:#0f0">START BOTS</button>
        <div id="l" style="margin-top:20px;border:1px solid #333;height:400px;overflow:auto;padding:10px;font-size:12px"></div>
        <script>
            function act(a){
                fetch('/cmd',{method:'POST',headers:{'Content-Type':'application/json'},
                body:JSON.stringify({a:a,u1:document.getElementById('u1').value,u2:document.getElementById('u2').value,p:document.getElementById('p').value,r:document.getElementById('r').value})})
            }
            setInterval(() => {
                fetch('/logs').then(r=>r.json()).then(d => {
                    document.getElementById('l').innerHTML = d.logs.map(log => {
                        let col = log.includes('SUCCESS') ? 'yellow' : (log.includes('CHAT') ? 'cyan' : 'white');
                        return `<div style="color:${col}">${log}</div>`;
                    }).join('');
                    document.getElementById('l').scrollTop = 999999;
                })
            }, 1500);
        </script>
    </body>
    """)

if __name__ == '__main__':
    port = int(os.environ.get("PORT", 5000))
    app.run(host='0.0.0.0', port=port)
