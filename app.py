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
import textdistance
from fuzzywuzzy import fuzz
import emoji

app = Flask(__name__)

# ================= CONFIG =================
BOT = {
    "user": "", "pass": "", "token": "", "ws": None,
    "status": "OFFLINE", "should_run": False, "room_id": None
}
ROOM_NAME = "testroom"  # default

CHAT_HISTORY = []

PERSONAS = ["RajBot", "ArjunBot"]

# Groq client (free tier - fast & instant)
groq_client = OpenAI(
    base_url="https://api.groq.com/openai/v1",
    api_key=os.environ.get("GROQ_API_KEY")
)

def perform_login():
    url = "https://api.howdies.app/api/login"
    try:
        resp = requests.post(url, json={"username": BOT["user"], "password": BOT["pass"]}, timeout=15)
        if resp.status_code == 200:
            data = resp.json()
            token = data.get("token") or data.get("data", {}).get("token")
            if token:
                BOT["token"] = token
                BOT["status"] = "LOGGED IN"
                return True
    except Exception as e:
        print(f"Login error: {e}")
    BOT["status"] = "LOGIN FAILED"
    return False

def on_open(ws):
    ws.send(json.dumps({"handler": "login", "username": BOT["user"], "password": BOT["pass"]}))
    time.sleep(0.5)
    ws.send(json.dumps({"handler": "joinchatroom", "id": str(time.time()), "name": ROOM_NAME, "roomPassword": ""}))
    BOT["status"] = "ONLINE"

def on_message(ws, message):
    try:
        data = json.loads(message)
        if data.get("handler") == "joinchatroom" and data.get("roomid"):
            BOT["room_id"] = data["roomid"]
        if data.get("handler") in ["chatroommessage", "message"]:
            sender = data.get("from") or data.get("username")
            text = data.get("text") or data.get("body")
            if sender and text:
                CHAT_HISTORY.append({"sender": sender, "text": text, "time": time.strftime("%H:%M")})
                if len(CHAT_HISTORY) > 50: CHAT_HISTORY.pop(0)
    except:
        pass

def send_msg(text):
    if BOT["ws"] and BOT["ws"].sock.connected and BOT["room_id"]:
        pkt = {
            "handler": "chatroommessage",
            "id": str(time.time()),
            "type": "text",
            "roomid": BOT["room_id"],
            "text": text,
            "url": "",
            "length": "0"
        }
        BOT["ws"].send(json.dumps(pkt))

def simulated_bot_to_bot():
    conversation = []      # context ke liye
    last_msgs = []         # repeat avoid cache

    while BOT["should_run"]:
        time.sleep(random.uniform(5, 16))  # real human-like gap

        if not BOT["ws"] or not BOT["ws"].sock.connected:
            continue

        sender = random.choice(PERSONAS)

        # Smart prompt for real human feel
        prompt = f"""You are {sender}, ek normal desi banda jo dost se Hinglish mein baat kar raha hai.
        Bilkul real aur casual rakh: chhote replies (kabhi 4-5 words, kabhi 1-2 line max).
        Funny, mast, slang daal sakta hai (bhai, yaar, arre, etc.).
        Emojis natural tareeke se daal (dil se).
        Har baar bilkul alag aur fresh likh – repeat mat karna.
        Previous chat:
        {chr(10).join(conversation[-6:])}
        [{sender}]: """

        try:
            response = groq_client.chat.completions.create(
                model="llama3-8b-instant",  # free, instant, high limits
                messages=[{"role": "user", "content": prompt}],
                max_tokens=60,
                temperature=1.2,         # zyada random & human
                top_p=0.92
            )
            raw_reply = response.choices[0].message.content.strip()
        except Exception as e:
            raw_reply = "Arre yaar thoda wait 😅"
            time.sleep(20)

        # Natural emoji add (random 60% chance)
        if random.random() < 0.6:
            raw_reply += " " + random.choice(["😂", "🔥", "😎", "🤣", "💀", "bro", "bhai", "yaar"])

        reply_text = raw_reply

        # Strong repeat check
        too_similar = False
        for prev in last_msgs[-6:]:
            similarity = fuzz.ratio(reply_text.lower(), prev.lower())
            if similarity > 75 or textdistance.levenshtein.normalized_distance(reply_text, prev) < 0.25:
                too_similar = True
                break

        if too_similar:
            reply_text += random.choice([" sahi pakda!", " 😂 kya baat", " mast bhai", " ab tu bata"])

        msg = f"[{sender}]: {reply_text}"
        send_msg(msg)
        CHAT_HISTORY.append({"sender": sender, "text": msg, "time": time.strftime("%H:%M")})

        conversation.append(f"[{sender}]: {reply_text}")
        last_msgs.append(reply_text)
        if len(last_msgs) > 10:
            last_msgs.pop(0)

# ===================== DASHBOARD =====================
UI_HTML = """
<!DOCTYPE html>
<html lang="hi">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <title>Bot Chat Dashboard</title>
    <style>
        body { font-family: monospace; background: #111; color: #eee; margin: 0; padding: 20px; }
        .container { max-width: 800px; margin: auto; }
        .box { background: #1a1a1a; padding: 15px; margin: 10px 0; border-radius: 8px; }
        input { width: 100%; padding: 10px; margin: 5px 0; background: #000; border: 1px solid #444; color: white; }
        button { padding: 12px 24px; background: #0066ff; color: white; border: none; cursor: pointer; margin: 10px 5px; border-radius: 6px; }
        button.stop { background: #cc0000; }
        #status { font-size: 18px; font-weight: bold; margin: 15px 0; }
        #chat { background: #000; border: 1px solid #333; padding: 15px; height: 500px; overflow-y: auto; font-size: 14px; line-height: 1.5; }
        .msg { margin: 10px 0; padding: 8px; border-radius: 6px; }
        .raj { background: #004080; text-align: left; }
        .arjun { background: #804000; text-align: right; }
    </style>
</head>
<body>
    <div class="container">
        <h2>Bot Chat Simulator (RajBot & ArjunBot)</h2>
        
        <div class="box">
            <label>Username: <input id="u" placeholder="Howdies Username"></label>
            <label>Password: <input id="p" type="password" placeholder="Password"></label>
        </div>
        
        <div class="box">
            <label>Room Name: <input id="r" placeholder="Room Name" value="testroom"></label>
        </div>
        
        <button onclick="connect()">Login & Start</button>
        <button class="stop" onclick="disconnect()">Logout & Stop</button>
        
        <div id="status">Status: OFFLINE</div>
        
        <div id="chat">
            <div class="msg">Yahan chat live dikhega... RajBot aur ArjunBot mast baat kar rahe honge 😎</div>
        </div>
    </div>

    <script>
        function connect() {
            const data = {
                u: document.getElementById('u').value.trim(),
                p: document.getElementById('p').value.trim(),
                r: document.getElementById('r').value.trim()
            };
            if (!data.u || !data.p || !data.r) return alert("Sab daal bhai!");
            fetch('/connect', {
                method: 'POST',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify(data)
            }).then(r => r.json()).then(d => alert(d.status));
        }
        
        function disconnect() {
            fetch('/disconnect', {method: 'POST'});
        }
        
        setInterval(() => {
            fetch('/status').then(r=>r.json()).then(d => {
                document.getElementById('status').innerText = `Status: ${d.status}`;
                const chatDiv = document.getElementById('chat');
                chatDiv.innerHTML = d.chat.map(m => {
                    const cls = m.sender.includes('Raj') ? 'raj' : 'arjun';
                    return `<div class="msg \( {cls}">[ \){m.time}] \( {m.sender}: \){m.text}</div>`;
                }).join('');
                chatDiv.scrollTop = chatDiv.scrollHeight;
            });
        }, 1500);
    </script>
</body>
</html>
"""

@app.route('/')
def index():
    return render_template_string(UI_HTML)

@app.route('/connect', methods=['POST'])
def connect():
    data = request.json
    global ROOM_NAME
    ROOM_NAME = data.get('r', 'testroom')
    
    BOT["user"] = data.get('u', '')
    BOT["pass"] = data.get('p', '')
    BOT["should_run"] = True
    
    if perform_login():
        ws_url = f"wss://app.howdies.app/howdies?token={BOT['token']}"
        ws = websocket.WebSocketApp(
            ws_url,
            on_open=on_open,
            on_message=on_message,
            on_error=lambda ws, err: print(f"WS Error: {err}"),
            on_close=lambda ws, c, m: setattr(BOT, "status", "DISCONNECTED")
        )
        BOT["ws"] = ws
        threading.Thread(target=ws.run_forever, kwargs={"sslopt": {"cert_reqs": ssl.CERT_NONE}}, daemon=True).start()
        
        threading.Thread(target=simulated_bot_to_bot, daemon=True).start()
        return jsonify({"status": "Chal gaya! Chat shuru 😎"})
    return jsonify({"status": "Login fail ho gaya, credentials check kar"})

@app.route('/disconnect', methods=['POST'])
def disconnect():
    BOT["should_run"] = False
    if BOT["ws"]:
        BOT["ws"].close()
    BOT["status"] = "OFFLINE"
    return jsonify({"status": "Stop ho gaya"})

@app.route('/status')
def status():
    chat_copy = CHAT_HISTORY[-40:]
    return jsonify({
        "status": BOT["status"],
        "chat": chat_copy
    })

if __name__ == '__main__':
    port = int(os.environ.get("PORT", 5000))
    app.run(host='0.0.0.0', port=port)
