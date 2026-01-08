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
from datetime import datetime

app = Flask(__name__)

# ================= CONFIGURATION =================
# Groq Client Setup (Free Tier & Fast)
GROQ_API_KEY = os.environ.get("GROQ_API_KEY") # Yahan apni API key set karein ya environment variable use karein
groq_client = OpenAI(
    base_url="https://api.groq.com/openai/v1",
    api_key=GROQ_API_KEY
)

# Global State
BOTS = {
    "1": {"user": "", "token": "", "ws": None, "status": "OFFLINE", "room_id": None, "partner": ""},
    "2": {"user": "", "token": "", "ws": None, "status": "OFFLINE", "room_id": None, "partner": ""}
}

SHARED_CONFIG = {
    "password": "",
    "room_name": "testroom",
    "is_running": False
}

CHAT_HISTORY = []  # Last 50 messages (Context for AI)
DEBUG_LOGS = []    # Terminal logs

# Smart Topic List (AI will use these to change flow)
TOPICS = [
    "latest south indian movies", "bangalore/delhi traffic situation", 
    "cricket world cup memories", "remote jobs vs office", 
    "street food (pani puri vs momos)", "funny childhood school memories",
    "expensive iphones logic", "weekend plans", "college life nostalgia",
    "current political scenarios (neutral view)"
]
CURRENT_TOPIC = random.choice(TOPICS)

# ================= SYSTEM OPTIMIZATION =================
def log(msg, type="INFO"):
    """Adds log to list with timestamp"""
    timestamp = datetime.now().strftime("%H:%M:%S")
    entry = f"[{timestamp}] [{type}] {msg}"
    print(entry)
    DEBUG_LOGS.append(entry)
    # Keep strictly limited for RAM
    if len(DEBUG_LOGS) > 300:
        DEBUG_LOGS.pop(0)

def memory_cleaner():
    """Background task: Clears logs every 15 mins to save RAM"""
    while True:
        time.sleep(900)  # 15 minutes
        DEBUG_LOGS.clear()
        CHAT_HISTORY.clear() # Clear chat context too to keep prompts fresh
        global CURRENT_TOPIC
        CURRENT_TOPIC = random.choice(TOPICS)
        log("🧹 System Auto-Cleanup: Logs cleared & Topic Rotated.", "SYSTEM")

threading.Thread(target=memory_cleaner, daemon=True).start()

# ================= AI BRAIN (GROQ LLAMA 3) =================
def get_ai_reply(sender_user, partner_user, chat_context):
    """Generates a Human-like Hinglish reply"""
    
    # Format context for Llama
    history_text = "\n".join([f"{m['sender']}: {m['text']}" for m in chat_context[-8:]])
    
    prompt = f"""
    You are {sender_user}, a smart Indian internet user. You are chatting with your close friend {partner_user}.
    
    **CONTEXT:**
    Current discussion topic: "{CURRENT_TOPIC}"
    Recent Chat History:
    {history_text}
    
    **INSTRUCTIONS:**
    1. **Language:** Hinglish (Roman Hindi + English mix). Use slang like "Bhai", "Yaar", "Sahi hai", "Lol".
    2. **Tone:** Casual, respectful but fun. No formal AI tone. Be brief (1-2 sentences).
    3. **Reaction:** React to what {partner_user} just said. If they asked something, answer it. If they joked, laugh.
    4. **Avoid:** Do NOT say "I am a bot". Do NOT repeat the same line. Do NOT write long essays.
    
    **YOUR REPLY:**
    """
    
    try:
        response = groq_client.chat.completions.create(
            model="llama3-8b-instant",  # Requested Model
            messages=[{"role": "user", "content": prompt}],
            max_tokens=60,
            temperature=1.2, # High creativity to sound human
            top_p=0.9
        )
        reply = response.choices[0].message.content.strip()
        
        # Clean up any accidental formatting
        reply = reply.replace(f"{sender_user}:", "").replace('"', '').strip()
        return reply
    except Exception as e:
        log(f"Groq API Error: {e}", "ERROR")
        return "Haan bhai sahi baat hai."

# ================= WEBSOCKET LOGIC =================
def perform_login(username, password):
    url = "https://api.howdies.app/api/login"
    try:
        resp = requests.post(url, json={"username": username, "password": password}, timeout=10)
        if resp.status_code == 200:
            data = resp.json()
            token = data.get("token") or data.get("data", {}).get("token")
            return token
    except Exception as e:
        log(f"Login failed for {username}: {e}", "ERROR")
    return None

def on_msg_handler(bot_id):
    def callback(ws, message):
        if not SHARED_CONFIG["is_running"]: return
        try:
            data = json.loads(message)
            my_user = BOTS[bot_id]["user"]
            partner = BOTS[bot_id]["partner"]
            
            # Room Join Capture
            if data.get("handler") == "joinchatroom" and data.get("roomid"):
                BOTS[bot_id]["room_id"] = data["roomid"]
                log(f"✅ {my_user} joined Room: {data['name']}", "SUCCESS")

            # Chat Message Received
            if data.get("handler") in ["chatroommessage", "message"]:
                sender = data.get("from") or data.get("username")
                text = data.get("text") or data.get("body")
                
                if sender and text:
                    # Save to history (Prevent duplicates)
                    if not CHAT_HISTORY or CHAT_HISTORY[-1]['text'] != text:
                        CHAT_HISTORY.append({"sender": sender, "text": text, "time": datetime.now().strftime("%H:%M")})
                    
                    # === REACTIVE TRIGGER ===
                    # Sirf tab reply karo jab message PARTNER ne bheja ho
                    if sender == partner:
                        threading.Thread(target=process_reply_task, args=(bot_id, text)).start()
                        
        except Exception as e:
            pass
    return callback

def process_reply_task(bot_id, incoming_text):
    """Waits and then replies"""
    # 1. Human Delay (Random 6s to 14s) - Fast reply = bot detection
    wait_time = random.uniform(6, 14)
    time.sleep(wait_time)
    
    if not SHARED_CONFIG["is_running"]: return

    # 2. Think (Generate Reply)
    my_user = BOTS[bot_id]["user"]
    partner = BOTS[bot_id]["partner"]
    
    reply = get_ai_reply(my_user, partner, CHAT_HISTORY)
    
    # 3. Type & Send
    send_message(bot_id, reply)

def send_message(bot_id, text):
    ws = BOTS[bot_id]["ws"]
    room_id = BOTS[bot_id]["room_id"]
    if ws and ws.sock and ws.sock.connected and room_id:
        pkt = {
            "handler": "chatroommessage",
            "id": str(time.time()),
            "type": "text",
            "roomid": room_id,
            "text": text,
            "url": "", "length": "0"
        }
        ws.send(json.dumps(pkt))
        log(f"📤 {BOTS[bot_id]['user']}: {text}", "CHAT")

def start_bot_connection(bot_id):
    user = BOTS[bot_id]["user"]
    pwd = SHARED_CONFIG["password"]
    
    token = perform_login(user, pwd)
    if not token:
        log(f"❌ Could not login {user}", "ERROR")
        return

    BOTS[bot_id]["token"] = token
    ws_url = f"wss://app.howdies.app/howdies?token={token}"
    
    ws = websocket.WebSocketApp(
        ws_url,
        on_open=lambda ws: (
            ws.send(json.dumps({"handler": "login", "username": user, "password": pwd})),
            time.sleep(1),
            ws.send(json.dumps({"handler": "joinchatroom", "id": str(time.time()), "name": SHARED_CONFIG["room_name"], "roomPassword": ""})),
            log(f"🌐 {user} Connected", "INFO")
        ),
        on_message=on_msg_handler(bot_id),
        on_error=lambda ws, e: log(f"WS Error {user}: {e}", "ERROR"),
        on_close=lambda ws, c, m: log(f"🔌 {user} Disconnected", "WARN")
    )
    BOTS[bot_id]["ws"] = ws
    ws.run_forever(sslopt={"cert_reqs": ssl.CERT_NONE})

# ================= WEB DASHBOARD =================
HTML_UI = """
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Hinglish TwinBots Control</title>
    <style>
        body { background-color: #0f0f0f; color: #e0e0e0; font-family: 'Segoe UI', monospace; padding: 20px; }
        .grid { display: grid; grid-template-columns: 1fr 1fr; gap: 20px; max-width: 1000px; margin: auto; }
        .card { background: #1e1e1e; padding: 20px; border-radius: 10px; border: 1px solid #333; }
        .full { grid-column: span 2; }
        h2 { color: #4caf50; border-bottom: 2px solid #333; padding-bottom: 10px; margin-top: 0; }
        label { display: block; margin: 10px 0 5px; color: #aaa; font-size: 0.9em; }
        input { width: 100%; padding: 10px; background: #2a2a2a; border: 1px solid #444; color: #fff; border-radius: 5px; box-sizing: border-box; }
        
        .btn-group { display: flex; gap: 10px; margin-top: 20px; }
        button { flex: 1; padding: 15px; border: none; border-radius: 5px; cursor: pointer; font-weight: bold; transition: 0.3s; }
        .start { background: #2e7d32; color: white; } .start:hover { background: #1b5e20; }
        .stop { background: #c62828; color: white; } .stop:hover { background: #b71c1c; }

        #terminal { height: 300px; overflow-y: scroll; background: #000; border: 1px solid #333; padding: 10px; font-family: monospace; font-size: 13px; color: #00ff00; }
        .log-CHAT { color: #00ffff; } .log-ERROR { color: #ff5252; } .log-SYSTEM { color: #ffeb3b; }
    </style>
</head>
<body>
    <div class="grid">
        <div class="card full">
            <h2>🤖 Hinglish Bot Controller (Llama 3)</h2>
        </div>

        <!-- Inputs -->
        <div class="card">
            <label>Bot 1 Username</label>
            <input id="u1" placeholder="Enter Username 1">
        </div>
        <div class="card">
            <label>Bot 2 Username</label>
            <input id="u2" placeholder="Enter Username 2">
        </div>
        <div class="card full">
            <div style="display: flex; gap: 20px;">
                <div style="flex:1">
                    <label>Shared Password</label>
                    <input id="pass" type="password" placeholder="Common Password">
                </div>
                <div style="flex:1">
                    <label>Room Name</label>
                    <input id="room" value="testroom">
                </div>
            </div>
            
            <div class="btn-group">
                <button class="start" onclick="action('start')">🚀 LOGIN & START CHAT</button>
                <button class="stop" onclick="action('stop')">🛑 LOGOUT & STOP</button>
            </div>
        </div>

        <!-- Debug Terminal -->
        <div class="card full">
            <label>Debugging Terminal (Payloads & Logs - Clears every 15m)</label>
            <div id="terminal">Waiting for commands...</div>
        </div>
    </div>

    <script>
        function action(type) {
            const data = {
                type: type,
                u1: document.getElementById('u1').value,
                u2: document.getElementById('u2').value,
                p: document.getElementById('pass').value,
                r: document.getElementById('room').value
            };
            fetch('/action', {
                method: 'POST',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify(data)
            }).then(r => r.json()).then(d => alert(d.message));
        }

        setInterval(() => {
            fetch('/logs').then(r => r.json()).then(data => {
                const term = document.getElementById('terminal');
                const wasScrolled = term.scrollTop === term.scrollHeight - term.clientHeight;
                
                term.innerHTML = data.logs.map(line => {
                    let cls = '';
                    if(line.includes('[CHAT]')) cls = 'log-CHAT';
                    if(line.includes('[ERROR]')) cls = 'log-ERROR';
                    if(line.includes('[SYSTEM]')) cls = 'log-SYSTEM';
                    return `<div class="${cls}">${line}</div>`;
                }).join('');
                
                // Auto scroll only if already at bottom
                term.scrollTop = term.scrollHeight;
            });
        }, 2000);
    </script>
</body>
</html>
"""

@app.route('/')
def index():
    return render_template_string(HTML_UI)

@app.route('/action', methods=['POST'])
def handle_action():
    data = request.json
    if data['type'] == 'stop':
        SHARED_CONFIG["is_running"] = False
        for bid in BOTS:
            if BOTS[bid]["ws"]: BOTS[bid]["ws"].close()
        return jsonify({"message": "All Bots Stopped."})

    # START
    u1, u2 = data['u1'], data['u2']
    pwd, room = data['p'], data['r']
    
    if not (u1 and u2 and pwd and room):
        return jsonify({"message": "Sab details bhar bhai!"})

    SHARED_CONFIG["password"] = pwd
    SHARED_CONFIG["room_name"] = room
    SHARED_CONFIG["is_running"] = True
    
    # Update Bot Config
    BOTS["1"].update({"user": u1, "partner": u2})
    BOTS["2"].update({"user": u2, "partner": u1})
    
    # Start Threads
    threading.Thread(target=start_bot_connection, args=("1",), daemon=True).start()
    threading.Thread(target=start_bot_connection, args=("2",), daemon=True).start()
    
    # Kickstart Conversation (After slight delay for login)
    threading.Thread(target=kickstart_conversation, daemon=True).start()
    
    return jsonify({"message": "Login Initiated! Check Terminal."})

def kickstart_conversation():
    """Bot 1 starts the chat automatically after connection"""
    time.sleep(8) # Wait for connections
    if SHARED_CONFIG["is_running"] and BOTS["1"]["ws"]:
        starters = [
            f"Aur bhai {BOTS['2']['user']}, kya chal raha hai aajkal?",
            f"Oye {BOTS['2']['user']}, kidhar gayab hai bhai?",
            f"Hello {BOTS['2']['user']}, mausam kaisa hai wahan?"
        ]
        msg = random.choice(starters)
        send_message("1", msg)
        log("🚀 Conversation Kickstarted automatically.", "SYSTEM")

@app.route('/logs')
def get_logs():
    return jsonify({"logs": DEBUG_LOGS})

if __name__ == '__main__':
    port = int(os.environ.get("PORT", 5000))
    app.run(host='0.0.0.0', port=port)
