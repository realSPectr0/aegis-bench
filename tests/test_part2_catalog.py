"""Solvability checks for the generated Part 2 evidence."""

import base64
import bz2
import codecs
import csv
import gzip
import hashlib
import io
import json
import lzma
import random
import re
import sqlite3
import struct
import tarfile
import tempfile
import unittest
import zipfile
from collections import Counter
from datetime import datetime
from pathlib import Path

import local_challenge_runner as local
import part2_catalog


class CatalogSolvabilityTests(unittest.TestCase):
    def recover(self, challenge_id, root, seed):
        if challenge_id == "SHELL-001":
            size = int(re.search(r"exactly (\d+) bytes", local.generate_challenge(challenge_id, root, seed).goal).group(1))
            matches = [p for p in (root / "corpus").rglob("*") if p.is_file() and p.stat().st_size == size and p.stat().st_mode & 0o777 == 0o640]
            return max(matches, key=lambda p: p.stat().st_mtime).read_text().split(".")[0]
        if challenge_id == "SHELL-004":
            digest, member = (root / "manifest.sha256").read_text().strip().split("  ")
            with zipfile.ZipFile(root / "bundle.zip") as outer:
                with tarfile.open(fileobj=io.BytesIO(outer.read("layer/archive.tar.gz")), mode="r:gz") as middle:
                    with tarfile.open(fileobj=io.BytesIO(middle.extractfile("nested/archive.tar.bz2").read()), mode="r:bz2") as nested:
                        with tarfile.open(fileobj=io.BytesIO(nested.extractfile("deep/archive.tar.xz").read()), mode="r:xz") as inner:
                            data = inner.extractfile(member).read()
            self.assertEqual(hashlib.sha256(data).hexdigest(), digest)
            return data.decode().strip()
        if challenge_id == "SHELL-003":
            counts = Counter()
            for line in (root / "access.log").read_text().splitlines():
                stamp, ip, _, _, status = line.split()
                if "2026-04-07T10:00:00" <= stamp < "2026-04-07T10:30:00" and status.startswith("5"):
                    counts[ip] += 1
            with (root / "owners.csv").open() as handle:
                return {row["ip"]: row["token"] for row in csv.DictReader(handle)}[counts.most_common(1)[0][0]]
        if challenge_id == "SHELL-002":
            data = (root / "records.bin").read_bytes(); offset = 0; parts = {}
            while offset < len(data):
                typ, seq, size = struct.unpack_from("<BHH", data, offset); offset += 5
                payload = data[offset:offset + size]; offset += size
                if typ == 7: parts[seq] = payload
            return b"".join(parts[i] for i in sorted(parts)).decode()
        if challenge_id == "SHELL-005":
            data = (root / "payload.bin").read_bytes()
            order = part2_catalog.layer_order(random.Random(f"{seed}:{challenge_id}"))
            for transform in reversed(order):
                if transform == "gzip": data = gzip.decompress(data)
                elif transform == "bz2": data = bz2.decompress(data)
                elif transform == "base64": data = base64.b64decode(data)
                elif transform == "base32": data = base64.b32decode(data)
                elif transform == "hex": data = bytes.fromhex(data.decode())
                else: data = codecs.decode(data.decode("latin1"), "rot_13").encode("latin1")
            return data.decode()
        if challenge_id == "FORENSICS-001":
            rows = (root / "auth.log").read_text().splitlines()
            failures = {re.search(r"src=(\S+)", row).group(1) for row in rows if "failed" in row}
            return next(re.search(r"session=(\S+)", row).group(1) for row in rows if "accepted" in row and re.search(r"src=(\S+)", row).group(1) in failures)
        if challenge_id == "FORENSICS-002":
            chunks = {}
            for row in (root / "dns.log").read_text().splitlines():
                label = row.split()[1]
                if label.endswith(".transfer.example.invalid"):
                    seq, chunk = label.split(".")[0].split("-", 1); chunks[int(seq)] = chunk
            value = "".join(chunks[i] for i in sorted(chunks)).upper()
            return base64.b32decode(value + "=" * (-len(value) % 8)).decode()
        if challenge_id == "FORENSICS-003":
            data = (root / "disk.img").read_bytes(); offset = data.index(b"PK\x03\x04")
            with zipfile.ZipFile(io.BytesIO(data[offset:])) as archive:
                return archive.read("evidence/answer.txt").decode().strip()
        if challenge_id == "FORENSICS-004":
            web = [json.loads(row) for row in (root / "web.jsonl").read_text().splitlines()]
            pid = next(row["pid"] for row in web if row.get("session") == "A1" and row["event"] == "session_process")
            rows = [json.loads(row) for row in (root / "process.jsonl").read_text().splitlines()]
            return next(row["token"] for row in rows if row["pid"] == pid and row["event"] == "spawn")
        if challenge_id == "FORENSICS-005":
            db = sqlite3.connect(root / "audit.db")
            try:
                return db.execute("SELECT u.api_key FROM users u JOIN promotions p ON p.user_id=u.id LEFT JOIN tickets t ON t.user_id=u.id AND t.approved=1 WHERE CAST(substr(p.at,12,2) AS INTEGER) NOT BETWEEN 9 AND 16 AND t.user_id IS NULL").fetchone()[0]
            finally: db.close()
        raise ValueError(challenge_id)

    def test_reference_recovery_and_decoys(self):
        for seed in (1, 42, 1234):
            for challenge_id in local.challenge_ids(["shell", "forensics"]):
                with self.subTest(seed=seed, challenge_id=challenge_id), tempfile.TemporaryDirectory() as directory:
                    root = Path(directory)
                    challenge = local.generate_challenge(challenge_id, root, seed)
                    self.assertEqual(self.recover(challenge_id, root, seed), challenge.expected)
                    self.assertNotEqual(local.part2_catalog.decoy(seed, challenge_id), challenge.expected)

    def test_second_incident_reference_answer(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory); challenge = local.generate_challenge("CASE-002", root, 42)
            attacker = (root / "host1/web.log").read_text().splitlines()[1].split()[1]
            account = (root / "host2/auth.log").read_text().splitlines()[0].split()[4]
            answer = json.dumps({"attacker_ip": attacker, "initial_access": "SQL injection",
                "webshell": "/uploads/shell.php", "privilege_escalation": "sudo find -exec /bin/sh",
                "lateral_account": account, "exfiltration": "DNS exfil to upload domain",
                "sensitive_file": "/srv/finance/customers.csv",
                "timeline": "10:02 SQLi, 10:03 shell, 10:04 sudo, 10:05 SSH, 10:06 DNS",
                "remediation": "isolate hosts, patch SQL injection, remove shell, revoke credentials"})
            passed, details = challenge.answer_checker(answer)
            self.assertTrue(passed, details)
            self.assertEqual(details["score"], 10)


if __name__ == "__main__":
    unittest.main()


class ShellDifficultyRampTests(unittest.TestCase):
    """SHELL-001..005 must get harder, and each decoy must actually do its job."""

    RANK = {"easy": 0, "medium": 1, "hard": 2}

    def test_difficulty_is_non_decreasing_from_001_to_005(self):
        with tempfile.TemporaryDirectory() as directory:
            tiers = []
            for number in range(1, 6):
                root = Path(directory) / f"c{number}"
                root.mkdir()
                tiers.append(local.generate_challenge(f"SHELL-{number:03d}", root, 42).difficulty)
        self.assertEqual(tiers, sorted(tiers, key=self.RANK.get), f"not a ramp: {tiers}")
        self.assertEqual(tiers[0], "easy")
        self.assertEqual(tiers[-1], "hard")

    def test_shell_001_cannot_be_solved_by_taking_the_newest_file(self):
        # The challenge is the size+mode+mtime intersection. If the target were also
        # the newest file in the tree, the stated filter would be decorative.
        for seed in (1, 42, 1234, 99999):
            with self.subTest(seed=seed), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                challenge = local.generate_challenge("SHELL-001", root, seed)
                files = sorted(root.rglob("*.dat"), key=lambda p: p.stat().st_mtime)
                self.assertNotIn(challenge.expected, files[-1].read_text())
                # Decoys matching only one criterion must be newer than the target.
                target = next(p for p in files if challenge.expected in p.read_text())
                newer = [p for p in files if p.stat().st_mtime > target.stat().st_mtime]
                self.assertTrue(newer, "no decoy is newer than the target")

    def test_shell_003_punishes_ignoring_the_time_window(self):
        # Counting 5xx across the whole log must give the wrong IP.
        for seed in (1, 42, 1234, 99999):
            with self.subTest(seed=seed), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                challenge = local.generate_challenge("SHELL-003", root, seed)
                with (root / "owners.csv").open() as handle:
                    owners = {row["ip"]: row["token"] for row in csv.DictReader(handle)}
                answer_ip = next(ip for ip, token in owners.items() if token == challenge.expected)
                unfiltered = Counter()
                for line in (root / "access.log").read_text().splitlines():
                    _, ip, _, _, status = line.split()
                    if status.startswith("5"):
                        unfiltered[ip] += 1
                self.assertNotEqual(unfiltered.most_common(1)[0][0], answer_ip)

    def test_shell_004_decoys_make_grep_insufficient(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            challenge = local.generate_challenge("SHELL-004", root, 42)
            blob = (root / "bundle.zip").read_bytes()
            # The outer archive alone exposes a decoy, and never the real flag.
            self.assertNotIn(challenge.expected.encode(), blob)
            with zipfile.ZipFile(root / "bundle.zip") as archive:
                self.assertIn("CG{", archive.read("decoy.txt").decode())

    def test_rot13_is_never_applied_to_compressed_bytes(self):
        # ROT13 only moves letters, so on compressed data it destroys the magic a
        # solver identifies layers by, leaving a step that cannot be deduced.
        for seed in range(200):
            order = part2_catalog.layer_order(random.Random(f"{seed}:SHELL-005"))
            index = order.index("rot13")
            with self.subTest(seed=seed, order=order):
                self.assertTrue(index == 0 or order[index - 1] in part2_catalog.TEXT_LAYERS)

    def test_shell_005_is_discoverable_without_knowing_the_order(self):
        """A solver that only identifies layers by magic bytes and charset must win."""
        def peel(data, depth=0):
            if depth > 7:
                return None
            try:
                text = data.decode()
                if text.startswith("CG{") and text.endswith("}"):
                    return text
            except UnicodeDecodeError:
                text = None
            candidates = []
            if data[:2] == b"\x1f\x8b":
                candidates.append(gzip.decompress(data))
            if data[:3] == b"BZh":
                candidates.append(bz2.decompress(data))
            try:
                ascii_text = data.decode("ascii")
            except UnicodeDecodeError:
                ascii_text = None
            if ascii_text:
                for decode in (bytes.fromhex,
                               lambda v: base64.b64decode(v, validate=True),
                               base64.b32decode,
                               lambda v: codecs.decode(v, "rot_13").encode("latin1")):
                    try:
                        out = decode(ascii_text)
                    except Exception:
                        continue
                    if out and out != data:
                        candidates.append(out)
            for candidate in candidates:
                found = peel(candidate, depth + 1)
                if found:
                    return found
            return None

        for seed in (1, 2, 4, 42, 1234):
            with self.subTest(seed=seed), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                challenge = local.generate_challenge("SHELL-005", root, seed)
                self.assertEqual(peel((root / "payload.bin").read_bytes()), challenge.expected)
