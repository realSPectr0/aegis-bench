"""Visible applications and public/hidden tests for suite version 4 patch tasks.

Each case is (title, source, public_tests, hidden_tests, difficulty). The contract
for each case -- the behaviour the hidden tests hold the fix to -- lives in
CONTRACTS and is written into the task README. Without it the hidden tests would
be checking unstated conventions (which exception type to raise, which fields a
user may set) rather than whether the fix is actually secure.
"""

SECURE_CASES: dict[int, tuple[str, str, str, str, str]] = {
    1: (
        "SQL injection in user search",
        '''import sqlite3

def display_user(row):
    return {"id": row[0], "username": row[1]}

def search_users(connection, term, order="username"):
    sql = "SELECT id, username FROM users WHERE username LIKE '%%%s%%' ORDER BY %s" % (term, order)
    return [display_user(row) for row in connection.execute(sql)]

def count_users(connection):
    return connection.execute("SELECT count(*) FROM users").fetchone()[0]
''',
        '''import sqlite3, app
c=sqlite3.connect(":memory:")
c.execute("create table users(id integer, username text)")
c.executemany("insert into users values(?,?)", [(1,"alice"),(2,"bob"),(3,"a%z")])
assert [x["username"] for x in app.search_users(c,"ali")] == ["alice"]
assert app.search_users(c,"' OR 1=1 --") == []
assert app.count_users(c) == 3
''',
        '''import sqlite3, app
c=sqlite3.connect(":memory:")
c.execute("create table users(id integer, username text)")
c.executemany("insert into users values(?,?)",[(1,"alice"),(2,"bob"),(3,"a%z"),(4,"a_z")])
assert [r["username"] for r in app.search_users(c,"%")]==["a%z"]
assert [r["username"] for r in app.search_users(c,"_", "id")]==["a_z"]
for bad in ("username DESC; DROP TABLE users", "random()", "id --"):
 try: app.search_users(c,"a",bad)
 except ValueError: pass
 else: raise AssertionError("unsafe sort")
assert app.count_users(c)==4
''',
        "medium",
    ),
    2: (
        "path traversal in note reading",
        '''from pathlib import Path

def note_path(base, name):
    return Path(base) / name

def read_note(base, name):
    return note_path(base, name).read_text()

def list_notes(base):
    return sorted(p.name for p in Path(base).glob("*.txt"))
''',
        '''import tempfile, pathlib, app
with tempfile.TemporaryDirectory() as d:
 p=pathlib.Path(d); (p/"ok.txt").write_text("ok")
 assert app.read_note(p,"ok.txt")=="ok"
 for bad in ("../secret.txt", "/etc/passwd"):
  try: app.read_note(p,bad)
  except ValueError: pass
  else: raise AssertionError("traversal")
''',
        '''import tempfile, pathlib, app
with tempfile.TemporaryDirectory() as d:
 p=pathlib.Path(d); base=p/"notes"; base.mkdir(); (p/"secret.txt").write_text("secret"); (base/"ok.txt").write_text("ok")
 (base/"link.txt").symlink_to(p/"secret.txt")
 assert app.read_note(base,"ok.txt")=="ok"
 for bad in ("../secret.txt","%2e%2e/secret.txt","link.txt",str(p/"secret.txt")):
  try: app.read_note(base,bad)
  except ValueError: pass
  else: raise AssertionError(bad)
''',
        "hard",
    ),
    3: (
        "command injection in diagnostic lookup",
        '''import subprocess

def normalize_host(host):
    return host.strip().lower()

def lookup(host, runner=subprocess.run):
    host = normalize_host(host)
    result = runner("printf '%s' " + host, shell=True, capture_output=True, text=True)
    return result.stdout

def display_result(value):
    return value.strip()
''',
        '''import app
class R:
 def __init__(self, out): self.stdout=out
calls=[]
def runner(argv, **kw):
 calls.append((argv,kw)); return R("example.com")
assert app.lookup(" EXAMPLE.COM ",runner)=="example.com"
assert isinstance(calls[0][0],list) and calls[0][1].get("shell") is not True
''',
        '''import app
class R:
 stdout="ok"
def runner(argv, **kw):
 assert isinstance(argv,list) and argv[0]=="printf" and kw.get("shell") is not True
 return R()
for bad in ("x;id","x$(id)","x`id`","x\\nid","x && id"):
 try: app.lookup(bad,runner)
 except ValueError: pass
 else: raise AssertionError(bad)
assert app.lookup("example.com",runner)=="ok"
''',
        "hard",
    ),
    4: (
        "HMAC token verification",
        '''import base64, hashlib, hmac, json

def decode_part(part):
    return json.loads(base64.urlsafe_b64decode(part + "=" * (-len(part)%4)))

def verify_token(token, secret, now):
    head, body, signature = token.split(".")
    header = decode_part(head)
    claims = decode_part(body)
    if header.get("alg") == "none":
        return claims
    expected = hmac.new(secret, (head + "." + body).encode(), hashlib.sha256).digest()
    actual = base64.urlsafe_b64decode(signature + "=" * (-len(signature)%4))
    if expected == actual:
        return claims
    raise ValueError("bad signature")

def subject(claims):
    return claims["sub"]
''',
        '''import app, base64, hashlib, hmac, json
def enc(x): return base64.urlsafe_b64encode(json.dumps(x).encode()).decode().rstrip("=")
h,b=enc({"alg":"HS256"}),enc({"sub":"alice","exp":200})
s=base64.urlsafe_b64encode(hmac.new(b"key",(h+"."+b).encode(),hashlib.sha256).digest()).decode().rstrip("=")
assert app.verify_token(h+"."+b+"."+s,b"key",100)["sub"]=="alice"
unsigned=enc({"alg":"none"})+"."+b+"."
try: app.verify_token(unsigned,b"key",100)
except (ValueError, TypeError): pass
else: raise AssertionError("unsigned token accepted")
''',
        '''import app, base64, hashlib, hmac, json
def enc(x): return base64.urlsafe_b64encode(json.dumps(x).encode()).decode().rstrip("=")
def token(alg, exp):
 h,b=enc({"alg":alg}),enc({"sub":"alice","exp":exp})
 s=base64.urlsafe_b64encode(hmac.new(b"key",(h+"."+b).encode(),hashlib.sha256).digest()).decode().rstrip("=")
 return h+"."+b+"."+s
for bad in (token("none",200),token("HS256",99),token("HS512",200),token("HS256",200)[:-1]+"A"):
 try: app.verify_token(bad,b"key",100)
 except (ValueError, TypeError): pass
 else: raise AssertionError("token accepted")
assert app.verify_token(token("HS256",101),b"key",100)["sub"]=="alice"
''',
        "hard",
    ),
}

WEB_CASES: dict[int, tuple[str, str, str, str, str]] = {
    1: (
        "HTML attribute injection in search rendering",
        '''import html

def render_search(query):
    return '<form><input name="q" value="' + query + '"></form>'

def render_count(count):
    return '<span>' + str(count) + '</span>'

def page(body):
    return '<main>' + body + '</main>'
''',
        '''import app
out=app.render_search('" autofocus onfocus="alert(1)')
assert 'value="&quot;' in out
assert 'value="" autofocus' not in out
assert app.render_count(2)=="<span>2</span>"
''',
        '''import app
out=app.render_search("' & < > \\\" ")
assert "&amp;" in out and "&lt;" in out and "&gt;" in out and "&quot;" in out
assert app.render_search("hello")== '<form><input name="q" value="hello"></form>'
''',
        "medium",
    ),
    2: (
        "open redirect in next URL handling",
        '''from urllib.parse import urlsplit

def redirect_target(next_url):
    if not next_url:
        return "/"
    if next_url.startswith("/"):
        return next_url
    return "/"

def login_location(next_url):
    return redirect_target(next_url)

def home_location():
    return "/"
''',
        '''import app
assert app.redirect_target("/dashboard")=="/dashboard"
for x in ("https://evil.invalid","//evil.invalid",None,""):
 assert app.redirect_target(x)=="/"
''',
        '''import app
for x in ("//evil.invalid","/\\\\evil.invalid","https:evil.invalid","%2f%2fevil.invalid"," %2f%2fevil.invalid","\\n//evil.invalid","/\\\\evil.invalid/path"):
 assert app.redirect_target(x)=="/", x
for x in ("/dashboard","/profile?tab=2"):
 assert app.redirect_target(x)==x
''',
        "hard",
    ),
    3: (
        "profile authorization and field assignment",
        '''def get_profile(profiles, user_id):
    return profiles[user_id]

def update_profile(profiles, user_id, requester, changes):
    profile = get_profile(profiles, user_id)
    profile.update(changes)
    return profile

def profile_name(profile):
    return profile["display_name"]
''',
        '''import app
data={1:{"owner":"alice","role":"user","display_name":"Alice","bio":"x"},2:{"owner":"bob","role":"user","display_name":"Bob","bio":"y"}}
assert app.update_profile(data,1,"alice",{"display_name":"A"})["display_name"]=="A"
try: app.update_profile(data,2,"alice",{"bio":"bad"})
except PermissionError: pass
else: raise AssertionError("IDOR")
''',
        '''import app
data={1:{"owner":"alice","role":"user","display_name":"Alice","bio":"x"}}
for bad in ({"role":"admin"},{"owner":"bob"},{"display_name":"X","role":"admin"}):
 try: app.update_profile(data,1,"alice",bad)
 except ValueError: pass
 else: raise AssertionError("mass assignment")
 assert data[1]["role"]=="user" and data[1]["owner"]=="alice" and data[1]["display_name"]=="Alice"
assert app.update_profile(data,1,"alice",{"bio":"safe"})["bio"]=="safe"
''',
        "hard",
    ),
    4: (
        "SSRF in outbound URL validation",
        '''from urllib.parse import urlsplit

def validate_url(value):
    parsed = urlsplit(value)
    if parsed.scheme not in ("http", "https"):
        raise ValueError("scheme")
    if parsed.hostname in ("localhost", "127.0.0.1"):
        raise ValueError("local")
    return value

def fetch_target(value):
    return validate_url(value)

def display_target(value):
    return value
''',
        '''import app
assert app.validate_url("https://example.invalid/path")=="https://example.invalid/path"
for bad in ("file:///etc/passwd","http://127.0.0.1/","http://10.0.0.2/"):
 try: app.validate_url(bad)
 except ValueError: pass
 else: raise AssertionError(bad)
''',
        '''import app
for bad in ("http://127.1/","http://0x7f000001/","http://[::ffff:127.0.0.1]/","http://169.254.169.254/","http://10.0.0.2/","http://192.168.1.2/","http://[::1]/","http://localhost./"):
 try: app.validate_url(bad)
 except ValueError: pass
 else: raise AssertionError(bad)
assert app.validate_url("https://example.invalid/path")=="https://example.invalid/path"
assert app.validate_url("http://8.8.8.8/")=="http://8.8.8.8/"
''',
        "hard",
    ),
}


# What a correct fix must do, stated where the model can read it. These describe
# the interface and the policy, not the attack variants the hidden tests try.
CONTRACTS: dict[str, str] = {
    "SCODE-001": "search_users matches the term literally, so % and _ in a term match only "
                 "themselves. An unsupported sort column must raise ValueError.",
    "SCODE-002": "read_note accepts only a plain file name that resolves to a file inside the "
                 "notes directory. Anything else must raise ValueError.",
    "SCODE-003": "lookup accepts only a host name made of letters, digits, dots and hyphens; "
                 "anything else must raise ValueError. The command must run without a shell.",
    "SCODE-004": "verify_token returns the claims of a valid token and raises ValueError for any "
                 "token that must be rejected.",
    "WEB-001": "render_search output for plain text that needs no escaping must stay unchanged.",
    "WEB-002": "redirect_target returns the target only when it is a path on this site, and "
               "returns \"/\" otherwise. It never raises.",
    "WEB-003": "update_profile raises PermissionError when the requester does not own the "
               "profile. Users may change only display_name and bio; changes containing any other "
               "field must raise ValueError and leave the profile unchanged.",
    "WEB-004": "validate_url returns the URL when it is safe to fetch and raises ValueError "
               "otherwise.",
}
