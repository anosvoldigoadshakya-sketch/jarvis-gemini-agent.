import os, hmac, time, uuid, threading
from collections import deque
from flask import Flask, jsonify, render_template, request
app = Flask(__name__)
WEB = os.getenv("JARVIS_WEB_TOKEN", "")
AGENT = os.getenv("JARVIS_AGENT_TOKEN", "")
tasks, queue, lock = {}, deque(), threading.Lock()
def ok(secret):
    auth = request.headers.get("Authorization", "")
    return bool(secret and auth.startswith("Bearer ") and hmac.compare_digest(auth[7:].strip(), secret))
def no(): return jsonify({"error":"Unauthorized"}), 401
@app.get("/")
def home(): return render_template("index.html")
@app.get("/api/health")
def health(): return jsonify({"ok":True})
@app.post("/api/tasks")
def add():
    if not ok(WEB): return no()
    body=request.get_json(silent=True) or {}
    goal=str(body.get("goal","")).strip()
    if not goal or len(goal)>500: return jsonify({"error":"Task must be 1 to 500 characters"}),400
    item={"id":uuid.uuid4().hex[:12],"goal":goal,"status":"queued","created_at":int(time.time()),"message":"Waiting for local agent"}
    with lock: tasks[item["id"]]=item; queue.append(item["id"])
    return jsonify(item),201
@app.get("/api/tasks")
def listing():
    if not ok(WEB): return no()
    with lock: return jsonify({"tasks":sorted(tasks.values(),key=lambda x:x["created_at"],reverse=True)[:30]})
@app.get("/api/agent/next")
def next_item():
    if not ok(AGENT): return no()
    with lock:
        while queue:
            item=tasks.get(queue.popleft())
            if item and item["status"]=="queued":
                item["status"]="claimed"; return jsonify({"task":item})
    return jsonify({"task":None})
@app.post("/api/agent/tasks/<item_id>/status")
def status(item_id):
    if not ok(AGENT): return no()
    body=request.get_json(silent=True) or {}
    value=str(body.get("status",""))
    if value not in {"running","completed","rejected","failed"}: return jsonify({"error":"Invalid status"}),400
    with lock:
        item=tasks.get(item_id)
        if not item: return jsonify({"error":"Task not found"}),404
        item["status"]=value; item["message"]=str(body.get("message",""))[:300]
        return jsonify(item)
if __name__=="__main__":
    if not WEB or not AGENT: raise RuntimeError("Set JARVIS_WEB_TOKEN and JARVIS_AGENT_TOKEN")
    app.run(host="0.0.0.0",port=int(os.getenv("PORT","10000")))
