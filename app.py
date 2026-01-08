import os
import json
import time
import threading
import random
import websocket
import ssl
import requests
import textdistance
import emoji  # <--- NEW LIBRARY
from flask import Flask, render_template_string, request, jsonify
from openai import OpenAI
from fuzzywuzzy import fuzz
from datetime import datetime

app = Flask(__name__)

# ================= CONFIGURATION =================
GROQ_API_KEY = os.environ.get("GROQ_API_KEY") 
groq_client = OpenAI(
    base_url="https://api.groq.com/openai/v1",
    api_key=GROQ_API_KEY
)

BOTS = {
    "1": {"user": "", "token": "", "ws": None, "room_id": None, "partner": ""},
    "2": {"user": "", "token": "", "ws": None, "room_id": None, "partner": ""}
}

SHARED_CONFIG = {
    "password": "", "room_name": "testroom", "is_running": False
}

CHAT_HISTORY = []
DEBUG_LOGS = []

TOPICS = [
    "virat kohli vs rohit sharma", "best web series on netflix", 
    "salary vs job satisfaction", "bangalore traffic rants", 
    "street food (mumbai vs delhi)", "funny school memories",
    "android vs iphone showoff", "weekend party plans",
    "gym lovers vs foodies", "office politics gossip"
]
CURRENT_TOPIC = random.choice(TOPICS)

# ================= SMART ENGINES =================

def smart_emoji_polisher(text):
    """
    Uses 'emoji' library to check if text needs more flavor.
    If no emoji is present, it detects mood and adds one.
    """
    # Check if AI already put an emoji (emoji.emoji_count counts emojis)
    if emoji.emoji_count(text) > 0:
        return text  # Already has emoji, don't overdo it.

    # Mood Analysis Keywords
    text_lower = text.lower()
    
    if any(x in text_lower for x in ['lol', 'haha', 'funny', 'mast', 'gajab']):
        return text + " " + random.choice(['😂', '🤣', '🔥'])
    
    if any(x in text_lower for x in ['bhai', 'yaar', 'bro', 'dude']):
        return text + " " + random.choice(['😎', '🤜🤛', '🤙'])
    
    if any(x in text_lower for x in ['love', 'pyar', 'dil', 'sahi']):
        return text + " " + random.choice(['❤️', '😍', '💯'])
    
    if any(x in text_lower for x in ['sad', 'bura', 'galat', 'fuck', 'shit']):
        return text + " " + random.choice(['💀', '🥲', '💔'])

    # Default fallback
    return text + " " + random.choice(['🤔', '😅', '✨'])

def get_brain_reply(sender, partner, context_msgs):
    """Generates Reply -> Checks Duplicates -> Polishes with Emoji"""
    
    history_str = "\n".join([f"{m['sender']}: {m['text']}" for m in context_msgs[-6:]])
    
    prompt = f"""
    Act as {sender}. You are chatting with {partner}.
    Topic: {CURRENT_TOPIC}
    History:
    {history_str}
    
    Directives:
    - Language: Casual Hinglish (Roman Hindi).
    - Tone: Friends talking on WhatsApp. Short, witty, natural.
    - Constraint: NO repetitions.
    - Output: Just the message text.
    """

    for _ in range(3): # 3 Attempts
        try:
            resp = groq_client.chat.completions.create(
                model="llama3-8b-instant",
                messages=[{"role": "user", "content": prompt}],
                max_tokens=55, temperature=1.1, top_p=0.9
            )
            raw = resp.choices[0].message.content.strip()
            clean_text = raw.replace(f"{sender}:", "").replace('"', '').strip()
            
            # --- FILTER 1: LENGTH ---
            if len(clean_text) < 2: continue

            # --- FILTER 2: DEDUPLICATION (Fuzzy + TextDistance) ---
            is_dup = False
            for old in context_msgs[-12:]:
                # Check similarity
                if fuzz.ratio(clean_text.lower(), old['text'].lower()) > 75: is_dup = True
                if textdistance.levenshtein.normalized_similarity(clean_text, old['text']) > 0.7: is_dup = True
                
            if is_dup:
                log(f"🧠 Brain: Rejected duplicate '{clean_text}'", "WARN")
                continue

            # --- ENGINE 3: EMOJI POLISHER ---
            final_text = smart_emoji_polisher(clean_text)
            
            return final_text

        except Exception as e:
            log(f"LLM Err: {e}", "ERROR")
            time.sleep(1)

    return "Haa bhai sahi hai 😂"

# ================= CORE SYSTEM =================

def log(msg, type="INFO"):
    t = datetime.now().strftime("%H:%M:%S")
    entry = f"[{t}] [{type}] {msg}"
    print(entry)
    DEBUG_LOGS.append(entry)
    if len(DEBUG_LOGS) > 300: DEBUG_LOGS.pop(0)

def maintenance_task():
    while True:
        time.sleep(900) # 15 mins
        DEBUG_LOGS.clear()
        if len(CHAT_HISTORY) > 10: del CHAT_HISTORY[:len(CHAT_HISTORY)-10]
        global CURRENT_TOPIC
        CURRENT_TOPIC = random.choice(TOPICS)
        log(f"♻️ Maintenance: Topic rotated to '{CURRENT_TOPIC}'", "SYSTEM")

threading.Thread(target=maintenance_task, daemon=True).start()

def perform_login(u, p):
    try:
        r = requests.post("https://api.howdies.app/api/login", json={"username":u,"password":p}, timeout=10)
        return r.json().get("token") or r.json().get("data",{}).get("token")
    except: return None

def ws_listener(bid):
    def on_msg(ws, msg):
        if not SHARED_CONFIG["is_running"]: return
        try:
            d = json.loads(msg)
            me = BOTS[bid]["user"]
            partner = BOTS[bid]["partner"]
            
            if d.get("handler") == "joinchatroom" and d.get("roomid"):
                BOTS[bid]["room_id"] = d["roomid"]
                log(f"✅ {me} Room Joined", "NET")

            if d.get("handler") in ["chatroommessage", "message"]:
                sender = d.get("from") or d.get("username")
                txt = d.get("text")
                if sender and txt:
                    # Update Memory
                    if not CHAT_HISTORY or CHAT_HISTORY[-1]['text'] != txt:
                        CHAT_HISTORY.append({"sender":sender, "text":txt, "time":datetime.now().strftime("%H:%M")})
                    
                    # Reactive Trigger
                    if sender == partner:
                        threading.Thread(target=reply_flow, args=(bid, txt)).start()
        except: pass
    return on_msg

def reply_flow(bid, incoming):
    # 1. Human Wait
    time.sleep(random.uniform(5, 12))
    if not SHARED_CONFIG["is_running"]: return

    # 2. Brain Process
    me = BOTS[bid]["user"]
    partner = BOTS[bid]["partner"]
    reply = get_brain_reply(me, partner, CHAT_HISTORY)

    # 3. Send
    ws = BOTS[bid]["ws"]
    rid = BOTS[bid]["room_id"]
    if ws and rid:
        ws.send(json.dumps({
            "handler": "chatroommessage", "id": str(time.time()),
            "type": "text", "roomid": rid, "text": reply, "url": "", "length": "0"
        }))
        log(f"🗣️ {me}: {reply}", "CHAT")

def connector(bid):
    u, p = BOTS[bid]["user"], SHARED_CONFIG["password"]
    token = perform_login(u, p)
    if not token: 
        log(f"Login Fail: {u}", "ERROR")
        return
    
    ws = websocket.WebSocketApp(
        f"wss://app.howdies.app/howdies?token={token}",
        on_open=lambda w: (
            w.send(json.dumps({"handler":"login","username":u,"password":p})),
            time.sleep(1),
            w.send(json.dumps({"handler":"joinchatroom","id":str(time.time()),"name":SHARED_CONFIG["room_name"],"roomPassword":""}))
        ),
        on_message=ws_listener(bid),
        on_error=lambda w,e: log(f"WS Err {u}: {e}", "ERROR")
    )
    BOTS[bid]["ws"] = ws
    ws.run_forever(sslopt={"cert_reqs": ssl.CERT_NONE})

# ================= UI =================
HTML = """
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <title>Emoji Smart Bot</title>
    <style>
        body { background: #000; color: #0f0; font-family: monospace; padding: 20px; }
        .box { border: 1px solid #333; padding: 15px; margin-bottom: 10px; border-radius: 5px; background: #111; }
        input { background: #222; border: 1px solid #444; color: #fff; padding: 8px; width: 100%; }
        button { width: 48%; padding: 10px; cursor: pointer; font-weight: bold; margin-top:10px; }
        .g { background: green; color:white; } .r { background: darkred; color:white; }
        #logs { height: 350px; overflow-y: auto; border: 1px solid #555; padding:5px; }
    </style>
</head>
<body>
    <div class="box">
        <h2>😎 Emoji-Smart Hinglish Bot</h2>
        <div style="display:flex; gap:10px">
            <input id="u1" placeholder="Bot 1 User">
            <input id="u2" placeholder="Bot 2 User">
        </div><br>
        <div style="display:flex; gap:10px">
            <input id="p" type="password" placeholder="Password">
            <input id="r" value="testroom">
        </div>
        <div style="display:flex; justify-content:space-between">
            <button class="g" onclick="run('start')">START SYSTEM</button>
            <button class="r" onclick="run('stop')">SHUTDOWN</button>
        </div>
    </div>
    <div class="box">
        <div>System Logs (Emoji Engine Active 🎭)</div>
        <div id="logs"></div>
    </div>
    <script>
        function run(a) {
            fetch('/act', {
                method:'POST', headers:{'Content-Type':'application/json'},
                body: JSON.stringify({t:a, u1:document.getElementById('u1').value, u2:document.getElementById('u2').value, p:document.getElementById('p').value, r:document.getElementById('r').value})
            }).then(r=>r.json()).then(d=>alert(d.m));
        }
        setInterval(() => {
            fetch('/logs').then(r=>r.json()).then(d => {
                const l = document.getElementById('logs');
                l.innerHTML = d.l.map(x => `<div style="color:${x.includes('CHAT')?'cyan':x.includes('WARN')?'orange':'lime'}">${x}</div>`).join('');
                l.scrollTop = l.scrollHeight;
            });
        }, 1500);
    </script>
</body>
</html>
"""

@app.route('/')
def h(): return render_template_string(HTML)

@app.route('/act', methods=['POST'])
def a():
    d = request.json
    if d['t'] == 'stop':
        SHARED_CONFIG["is_running"] = False
        for b in BOTS.values(): 
            if b['ws']: b['ws'].close()
        return jsonify({"m": "Stopped"})
    
    SHARED_CONFIG["password"] = d['p']
    SHARED_CONFIG["room_name"] = d['r']
    SHARED_CONFIG["is_running"] = True
    BOTS["1"].update({"user":d['u1'], "partner":d['u2']})
    BOTS["2"].update({"user":d['u2'], "partner":d['u1']})
    
    threading.Thread(target=connector, args=("1",), daemon=True).start()
    threading.Thread(target=connector, args=("2",), daemon=True).start()
    threading.Thread(target=kick, daemon=True).start()
    return jsonify({"m": "Starting..."})

def kick():
    time.sleep(10)
    if SHARED_CONFIG["is_running"] and BOTS["1"]["ws"]:
        msg = f"Aur bhai {BOTS['2']['user']}, kidhar hai aajkal? 😎"
        ws = BOTS["1"]["ws"]
        rid = BOTS["1"]["room_id"]
        if rid:
            ws.send(json.dumps({"handler":"chatroommessage","id":str(time.time()),"type":"text","roomid":rid,"text":msg,"url":"","length":"0"}))
            log(f"🚀 Kick: {msg}", "SYSTEM")

@app.route('/logs')
def l(): return jsonify({"l": DEBUG_LOGS})

if __name__ == '__main__':
    port = int(os.environ.get("PORT", 5000))
    app.run(host='0.0.0.0', port=port)
