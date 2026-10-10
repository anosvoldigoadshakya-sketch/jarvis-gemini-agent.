import os, re, time
import requests, pyautogui
from PIL import Image
from google import genai

SERVER_URL = os.environ.get("JARVIS_SERVER_URL", "").rstrip("/")
AGENT_TOKEN = os.environ.get("JARVIS_AGENT_TOKEN", "")
MODEL = os.environ.get("GEMINI_MODEL", "gemini-2.5-flash")
POLL_SECONDS, MAX_STEPS = 3, 15
pyautogui.FAILSAFE = True
pyautogui.PAUSE = 0.5
client = genai.Client()

def headers():
    return {"Authorization": f"Bearer {AGENT_TOKEN}"}

def update_status(job_id, status, message):
    try:
        requests.post(f"{SERVER_URL}/api/agent/tasks/{job_id}/status", headers=headers(),
                      json={"status": status, "message": message[:300]}, timeout=15).raise_for_status()
    except requests.RequestException as exc:
        print(f"[warning] Could not update cloud status: {exc}")

def ask_gemini(goal):
    path = "agent_view.png"
    try:
        pyautogui.screenshot(path)
        with Image.open(path) as im:
            image = im.copy()
        width, height = pyautogui.size()
        prompt = f"""You control a Windows desktop for this task: {goal!r}.
Screen size is {width}x{height}, origin top-left.
Return exactly ONE command and nothing else:
CLICK(x, y)
TYPE("text")
PRESS("key")
HOTKEY("ctrl", "s")
DONE
Do not propose shell commands, downloads, purchases, sending messages, deleting files,
changing security settings, entering passwords, or actions outside the task.
Use only ordinary visible UI actions and screen coordinates."""
        response = client.models.generate_content(model=MODEL, contents=[image, prompt])
        return (response.text or "").strip().replace("```", "").strip()
    finally:
        try: os.remove(path)
        except OSError: pass

def parse_action(text, sw, sh):
    m = re.fullmatch(r"CLICK\s*\(\s*(\d+)\s*,\s*(\d+)\s*\)", text)
    if m:
        x, y = map(int, m.groups())
        return ("click", (x, y)) if x < sw and y < sh else None
    m = re.fullmatch(r'TYPE\s*\(\s*"([^"\n]*)"\s*\)', text)
    if m and len(m.group(1)) <= 200: return ("type", (m.group(1),))
    m = re.fullmatch(r"PRESS\s*\(\s*['\"]([a-zA-Z0-9_]+)['\"]\s*\)", text)
    if m:
        key = m.group(1).lower()
        if key in {"enter","tab","escape","backspace","delete","up","down","left","right","home","end","space"}:
            return ("press", (key,))
    m = re.fullmatch(r"HOTKEY\s*\(\s*['\"](ctrl|alt|shift)['\"]\s*,\s*['\"]([a-zA-Z0-9_]+)['\"]\s*\)", text)
    if m:
        mod, key = m.group(1).lower(), m.group(2).lower()
        if key in {"a","c","v","x","z","y","s","f","w","t","r","tab","enter"}:
            return ("hotkey", (mod, key))
    return None

def execute(action):
    kind, args = action
    if kind == "click": pyautogui.click(*args)
    elif kind == "type": pyautogui.write(args[0], interval=0.02)
    elif kind == "press": pyautogui.press(args[0])
    elif kind == "hotkey": pyautogui.hotkey(*args)

def run_task(job):
    jid, goal = job["id"], job["goal"]
    update_status(jid, "running", "Task started locally.")
    print(f"\nWebsite task: {goal}\nFailsafe: move mouse to a screen corner to stop.")
    for step in range(1, MAX_STEPS + 1):
        try: command = ask_gemini(goal)
        except Exception as exc:
            update_status(jid, "failed", f"Gemini error: {exc}")
            print(f"Gemini error: {exc}")
            return
        if command.upper() == "DONE":
            update_status(jid, "completed", "Gemini reported the task complete.")
            print("Task marked complete.")
            return
        action = parse_action(command, *pyautogui.size())
        if not action:
            update_status(jid, "rejected", f"Blocked unsupported action: {command[:150]}")
            print(f"Blocked unsupported action: {command}")
            return
        print(f"Step {step}/{MAX_STEPS}: proposed action: {command}")
        if input("Approve this action? [y/N] ").strip().lower() != "y":
            update_status(jid, "rejected", "Stopped by local user before action.")
            print("Stopped.")
            return
        try:
            execute(action)
            time.sleep(1.5)
        except Exception as exc:
            update_status(jid, "failed", f"Local action error: {exc}")
            print(f"Action failed: {exc}")
            return
    update_status(jid, "completed", f"Stopped at safety limit of {MAX_STEPS} steps.")

def main():
    if not SERVER_URL.startswith(("https://", "http://127.0.0.1")):
        raise SystemExit("Set JARVIS_SERVER_URL to your HTTPS Render URL.")
    if not AGENT_TOKEN: raise SystemExit("Set JARVIS_AGENT_TOKEN.")
    print("Jarvis local agent running. Keep this terminal open.")
    while True:
        try:
            r = requests.get(f"{SERVER_URL}/api/agent/next", headers=headers(), timeout=20)
            r.raise_for_status()
            job = r.json().get("task")
            if job: run_task(job)
            else: time.sleep(POLL_SECONDS)
        except KeyboardInterrupt:
            print("\nAgent stopped."); break
        except requests.RequestException as exc:
            print(f"Cloud connection error: {exc}"); time.sleep(8)

if __name__ == "__main__": main()
