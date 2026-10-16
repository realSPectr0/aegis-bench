import sqlite3,subprocess,os,datetime
from flask import Flask,jsonify,request,redirect
from passlib.hash import bcrypt_sha256
app=Flask(__name__)
DB_PATH=os.path.join("platform","CTFd","ctfd.db")
PROC=None
@app.route("/")
def index():
    ps,cs,stats,active=[],[],[],PROC is not None and PROC.poll() is None
    if os.path.exists(DB_PATH):
        try:
            conn=sqlite3.connect(DB_PATH)
            ps=[r[0] for r in conn.execute("SELECT name FROM users WHERE type='user' AND name != 'user0'").fetchall()]
            p=request.args.get('p')
            if p:
                rows=conn.execute("SELECT c.name,(SELECT date FROM tracking WHERE user_id=u.id AND type='challenges.open' AND target=c.id ORDER BY date LIMIT 1),(SELECT date FROM tracking WHERE user_id=u.id AND type='challenges.download' AND target=c.id ORDER BY date LIMIT 1),(SELECT sub.date FROM submissions sub JOIN solves sol ON sub.id=sol.id WHERE sol.user_id=u.id AND sol.challenge_id=c.id ORDER BY sub.date LIMIT 1),(SELECT COUNT(*) FROM tracking WHERE user_id=u.id AND type='anti_cheat.alert' AND target=c.id) FROM challenges c JOIN users u ON u.name=? ",(p,)).fetchall()
                for r in rows:
                    dur=""
                    if r[1] and r[3]:
                        try:
                            from datetime import datetime as dt
                            fmt="%Y-%m-%d %H:%M:%S.%f"
                            dur=str(dt.strptime(r[3].split('+')[0],fmt)-dt.strptime(r[1].split('+')[0],fmt)).split('.')[0]
                        except:dur="Err"
                    stats.append(f"<tr><td>{r[0]}</td><td>{r[1]}</td><td>{r[2]}</td><td>{r[3]}</td><td>{dur}</td><td>{'!' if r[4]>0 else ''}</td></tr>")
            cs=conn.execute("SELECT c.name,COUNT(s.id) FROM challenges c LEFT JOIN solves s ON c.id=s.challenge_id GROUP BY c.id").fetchall()
            conn.close()
        except:pass
    u_h="".join([f"<li><a href='/?p={p}'>{p}</a></li>" for p in ps])
    cs_h="".join([f"<tr><td>{n}</td><td>{s}</td></tr>" for n,s in cs])
    s_h="".join(stats)
    ctrl=f"<button onclick=\"fetch('/start').then(()=>location.reload())\">Start</button>" if not active else f"<button onclick=\"fetch('/stop').then(()=>location.reload())\">Stop</button>"
    main=""
    if active:
        if request.args.get('p'): main=f"<h2>{p}</h2><table border=1><tr><th>Chall</th><th>Open</th><th>Down</th><th>Solve</th><th>Time</th><th>Cheat</th></tr>{s_h}</table>"
        else: main=f"<h2>Solves</h2><table border=1><tr><th>Chall</th><th>Solves</th></tr>{cs_h}</table>"
        main+=f"<br><form action='/adduser' method='POST'><input name='n' placeholder='User'><input name='pw' type='password' placeholder='Pass'><button>Add User</button></form>"
    side=f"<div style='width:150px;background:#eee;min-height:100vh;padding:10px'><a href='/'>Dashboard</a><ul>{u_h}</ul></div>" if active else ""
    return f"<html><body style='display:flex;margin:0;font-family:sans-serif'>{side}<div style='padding:20px'><h1>CTFd</h1>{ctrl}{main}</div></body></html>"
@app.route("/start")
def start():
    global PROC
    if os.path.exists(DB_PATH): os.remove(DB_PATH)
    if PROC is None or PROC.poll() is not None: PROC=subprocess.Popen(["../venv/bin/python","serve.py"],cwd="platform")
    return jsonify(s=1)
@app.route("/stop")
def stop():
    global PROC
    if PROC: PROC.terminate(); PROC=None
    return jsonify(s=1)
def create_user(n, pw_raw):
    pw = bcrypt_sha256.hash(pw_raw)
    conn = sqlite3.connect(DB_PATH)
    conn.execute("INSERT INTO users (name,password,email,type,verified,hidden,banned,created) VALUES (?,?,?, 'user', 1, 0, 0, ?)",(n,pw,f"{n}@ctf.io",datetime.datetime.utcnow()))
    conn.commit()
    conn.close()

@app.route("/adduser",methods=["POST"])
def adduser():
    # Check if user0 exists
    conn = sqlite3.connect(DB_PATH)
    user0_exists = conn.execute("SELECT 1 FROM users WHERE name='user0'").fetchone()
    conn.close()

    # Simulate input for user0 if it doesn't exist
    if not user0_exists:
        create_user('user0', 'user0')

    # Process the actual requested user
    create_user(request.form['n'], request.form['pw'])
    
    return redirect("/")
if __name__=="__main__": app.run(port=5000)
