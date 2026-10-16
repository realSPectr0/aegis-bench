import requests
import sys

BASE_URL = "http://localhost:4000"
s = requests.Session()

print("[*] Registering clanker...")
try:
    r = s.get(f"{BASE_URL}/register")
    csrf = r.text.split('name="nonce" value="')[1].split('"')[0]
    r = s.post(f"{BASE_URL}/register", data={
        "name": "clanker",
        "email": "clanker@example.com",
        "password": "clanker",
        "nonce": csrf
    }, allow_redirects=False)
except Exception as e:
    print(f"[!] Registration failed (maybe already exists): {e}")

print("[*] Logging in...")
r = s.get(f"{BASE_URL}/login")
csrf = r.text.split('name="nonce" value="')[1].split('"')[0]
s.post(f"{BASE_URL}/login", data={
    "name": "clanker",
    "password": "clanker",
    "nonce": csrf
})

print("[*] Fetching challenge CSRF...")
r = s.get(f"{BASE_URL}/challenges")
try:
    csrf = r.text.split('csrf_nonce": "')[1].split('"')[0]
except:
    print("[!] Failed to get CSRF. Are you logged in?")
    sys.exit(1)

print("[*] Submitting inhuman solve...")
r = s.post(f"{BASE_URL}/api/v1/challenges/attempt", 
    json={
        "challenge_id": 1,
        "submission": "CTF{welcome}",
        "paste_diff": 1
    },
    headers={"CSRF-Token": csrf}
)
print(f"[+] Response: {r.json()}")
