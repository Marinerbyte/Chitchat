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

# Topics for bots to discuss
TOPICS = ["Bangalore traffic", "Virat Kohli's form", "Latest Netflix shows", "Street food", "Gym motivation", "AI bots", "Weather"]

# ================= 🧠 AI BRAIN =================

def get_ai_reply(bot_name, user, msg, current_topic):
    try:
        prompt = (f"You are {bot_name}. Talking to your friend {user} about {current_topic}. "
                  "Reply in 1 short Hinglish line. Be casual, use 'yaar', 'bro'. "
                  "Don't be a bot. If the chat is dying, ask a random question.")
        resp = groq_client.chat.completions.create(
            model="llama3-8b-instant",
            messages=[{"role": "system", "content": prompt}, {"role": "user", "content": msg}],
            max_tokens=50, temperature=1.1
        )
        return resp.choices[0].message.content.strip()
    except: return random.choice(["Aur bata?", "Sahi hai yaar", "Hmm..", "😂"])

# ================= 🤖 CONVERSATION BOT ENGINE =================

class MasterBot:
    def __init__(self, name, partner, is_starter=False):
        self.name = name
        self.partner = partner
        self.is_starter = is_starter
        self.ws = None
        self.token = None
        self.room_id = None
        self.current_topic = random.choice(TOPICS)
        self.ua = "Mozilla/5.0 (iPhone; CPU iPhone OS 17_4 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.4 Mobile/15E148 Safari/604.1"

    def log(self, msg, tag="INFO"):
        t = datetime.now().strftime("%H:%M:%S")
        LOGS.append(f"[{t}] [{tag}] [{self.name}] {msg}")

    def login(self):
        try:
            r = requests.post("https://api.howdies.app/api/login", 
                json={"username": self.name, "password": SYSTEM_STATE['password']}, 
                headers={"User-Agent": self.ua}, timeout=10)
            res = r.json()
            self.token = res.get("token") or res.get("data", {}).get("token")
            return True if self.token else False
        except: return False

    def on_open(self, ws):
        self.log("Socket Connected", "NET")
        ws.send(json.dumps({"handler": "login", "username": self.name, "password": SYSTEM_STATE['password']}))
        time.sleep(4)
        ws.send(json.dumps({"handler": "joinchatroom", "name": SYSTEM_STATE['room_name'], "roomPassword": ""}))

    def on_message(self, ws, msg):
        try:
            d = json.loads(msg)
            if d.get("handler") == "joinchatroom" and d.get("roomid"):
                self.room_id = d.get("roomid")
                self.log("Entered Room", "LIVE")
                if self.is_starter:
                    threading.Timer(10, self.auto_start).start()

            if d.get("handler") in ["chatroommessage", "message"]:
                sender, text = d.get("from") or d.get("username"), d.get("text", "")
                if sender and sender != self.name:
                    # Reply logic: If partner speaks OR bot is mentioned
                    if sender == self.partner or self.name.lower() in text.lower():
                        threading.Thread(target=self.reply_logic, args=(sender, text)).start()
        except: pass

    def auto_start(self):
        """Kickstarts the conversation if silent"""
        if self.ws and self.room_id:
            msg = f"Aur @{self.partner}, kya scene? {self.current_topic} ke baare me suna?"
            self.send_chat(msg)

    def reply_logic(self, sender, text):
        # Human delay
        time.sleep(random.uniform(4, 8))
        reply = get_ai_reply(self.name, sender, text, self.current_topic)
        if reply: self.send_chat(reply)

    def send_chat(self, text):
        if self.ws and self.room_id:
            try:
                # Typing indicator for realism
                self.ws.send(json.dumps({"handler": "starttyping", "roomid": self.room_id}))
                time.sleep(len(text) * 0.1)
                self.ws.send(json.dumps({"handler": "chatroommessage", "type": "text", "roomid": self.room_id, "text": text}))
                self.log(f"Sent: {text}", "CHAT")
            except: pass

    def connect(self):
        if not self.login(): return
        def run():
            self.ws = websocket.WebSocketApp(
                f"wss://app.howdies.app/howdies?token={self.token}",
                header={"User-Agent": self.ua},
                on_open=self.on_open, on_message=self.on_message,
                on_close=lambda ws, a, b: self.reconnect()
            )
            self.ws.run_forever(sslopt={"cert_reqs": ssl.CERT_NONE}, ping_interval=30)
        threading.Thread(target=run, daemon=True).start()

    def reconnect(self):
        if SYSTEM_STATE['running']:
            time.sleep(15)
            self.connect()

# ================= ⚡ FLASK UI & CONTROL =================

@app.route('/cmd', methods=['POST'])
def cmd():
    data = request.json
    if data['a'] == 'start':
        SYSTEM_STATE.update({"password": data['p'], "room_name": data['r'], "running": True})
        # Bot 1 is the Icebreaker (Starter)
        BOTS["1"] = MasterBot(data['u1'], data['u2'], is_starter=True)
        BOTS["2"] = MasterBot(data['u2'], data['u1'], is_starter=False)
        BOTS["1"].connect()
        threading.Timer(10, BOTS["2"].connect).start()
        return jsonify({"s": "ok"})
    if data['a'] == 'stop':
        SYSTEM_STATE['running'] = False
        LOGS.clear()
        return jsonify({"s": "wiped"})
    return jsonify({"s": "err"})

@app.route('/logs')
def get_logs():
    return jsonify({"logs": LOGS[-25:], "status": "Running" if SYSTEM_STATE['running'] else "Stopped"})

@app.route('/')
def index():
    return render_template_string("""
    <body style="background:#000;color:#0f0;font-family:monospace;padding:20px">
        <h2>Aura-Link V9 (Conversation Master)</h2>
        <div class="card">
            <input id="u1" placeholder="Bot 1 (Starter)">
            <input id="u2" placeholder="Bot 2 (Responder)">
            <input id="p" type="password" placeholder="Password">
            <input id="r" placeholder="Room Name">
            <br><br>
            <button onclick="act('start')" style="padding:10px;background:#0f0">START CONVERSATION</button>
            <button onclick="act('stop')" style="padding:10px;background:red;color:white">STOP & WIPE</button>
        </div>
        <div id="log" style="margin-top:20px;border:1px solid #222;height:400px;overflow:auto;padding:10px"></div>
        <script>
            function act(a){
                fetch('/cmd',{method:'POST',headers:{'Content-Type':'application/json'},
                body:JSON.stringify({a:a,u1:document.getElementById('u1').value,u2:document.getElementById('u2').value,p:document.getElementById('p').value,r:document.getElementById('r').value})});
            }
            setInterval(() => {
                fetch('/logs').then(r=>r.json()).then(d => {
                    document.getElementById('log').innerHTML = d.logs.map(l => {
                        let col = l.includes('CHAT') ? 'cyan' : (l.includes('LIVE') ? 'yellow' : 'white');
                        return `<div style="color:${col}">${l}</div>`;
                    }).join('');
                    document.getElementById('log').scrollTop = 99999;
                })
            }, 1500);
        </script>
    </body>
    """)

if __name__ == '__main__':
    port = int(os.environ.get("PORT", 5000))
    app.run(host='0.0.0.0', port=port)
