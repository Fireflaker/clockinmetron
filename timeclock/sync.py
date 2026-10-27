"""Sync through one private GitHub Gist (free). The phone app (android/app.js) does exactly the same.

The gist holds one file, clockinmetron.json = {"tags": [...], "log": [...], "schedules": [...]}.
Each device remembers `base`, the hash of what it last synced, and on every sync:
    nothing changed            -> nothing to do
    only this device changed   -> upload
    only the gist changed      -> take the gist's copy
    both changed (offline use) -> merge: union of tags / log rows / schedules (this device wins ties), upload
Settings (theme, location, token) stay on each device.
"""
import hashlib
import json
import urllib.error
import urllib.request

FILE = "clockinmetron.json"
API = "https://api.github.com"


def digest(doc):
    """Hash of the synced content. Schedule `last` (bookkeeping) is left out."""
    canon = [
        sorted([t["name"], float(t["x"]), float(t["y"])] for t in doc["tags"]),
        sorted(([float(r[0]), r[1], r[2] if r[2] is None else float(r[2]), r[3] if r[3] is None else float(r[3])]
                for r in doc["log"]), key=lambda r: r[0]),
        sorted([int(s["id"]), s["name"], s["hhmm"], s["days"], bool(s["on"])] for s in doc["schedules"]),
    ]
    return hashlib.sha1(json.dumps(canon, separators=(",", ":")).encode()).hexdigest()


def compact(log):
    out = []
    for r in sorted(log, key=lambda r: r[0]):
        if (not out and r[1] is None) or (out and list(out[-1][1:]) == list(r[1:])):
            continue
        out.append(list(r))
    return out


def merge(remote, local):
    tags = {t["name"]: t for t in remote["tags"]}
    tags.update({t["name"]: t for t in local["tags"]})
    log = {float(r[0]): r for r in remote["log"]}
    log.update({float(r[0]): r for r in local["log"]})
    sch = {int(s["id"]): dict(s) for s in remote["schedules"]}
    for s in local["schedules"]:
        old = sch.get(int(s["id"]))
        sch[int(s["id"])] = dict(s, last=max((old or {}).get("last") or 0, s.get("last") or 0) or None)
    return {"tags": list(tags.values()), "log": compact(log.values()), "schedules": list(sch.values())}


def decide(base, local, remote):
    """-> (doc_to_upload or None, doc_to_adopt or None, new_base)."""
    hl = digest(local)
    if remote is None:
        return local, None, hl
    hr = digest(remote)
    if hl == hr:
        return None, None, hl
    if hr == base:
        return local, None, hl
    if hl == base:
        return None, remote, hr
    merged = merge(remote, local)
    return merged, merged, digest(merged)


class GistError(Exception):
    pass


class Gist:
    def __init__(self, token, gist_id=None):
        self.token, self.id = token.strip(), gist_id

    def _req(self, method, url, body=None):
        req = urllib.request.Request(url if url.startswith("http") else API + url, method=method,
                                     data=None if body is None else json.dumps(body).encode(),
                                     headers={"Authorization": f"Bearer {self.token}",
                                              "Accept": "application/vnd.github+json",
                                              "User-Agent": "clockinmetron"})
        try:
            with urllib.request.urlopen(req, timeout=20) as r:
                data = r.read()
        except urllib.error.HTTPError as e:
            msg = {401: "token rejected", 404: "gist not found",
                   403: "token lacks Gist permission (edit token → Account tab → Gists: Read and write)"}.get(e.code)
            raise GistError(msg or f"GitHub error {e.code}") from None
        except OSError as e:
            raise GistError(f"offline ({e})") from None
        return data if url.startswith("http") else json.loads(data or b"null")

    def find(self):
        """Look for an existing clockinmetron gist on this account (so other devices only need the token)."""
        for page in range(1, 11):
            gists = self._req("GET", f"/gists?per_page=100&page={page}")
            for g in gists:
                if FILE in g["files"]:
                    self.id = g["id"]
                    return self.id
            if len(gists) < 100:
                return None

    def load(self):
        f = self._req("GET", f"/gists/{self.id}")["files"].get(FILE)
        if not f:
            return None
        text = self._req("GET", f["raw_url"]).decode() if f.get("truncated") else f["content"]
        return json.loads(text)

    def save(self, doc):
        body = {"files": {FILE: {"content": json.dumps(doc, separators=(",", ":"))}}}
        if self.id:
            self._req("PATCH", f"/gists/{self.id}", body)
        else:
            body.update(public=False, description="clockinmetron data (https://github.com/Fireflaker/clockinmetron)")
            self.id = self._req("POST", "/gists", body)["id"]


def sync_once(gist, base, local, first="merge"):
    """Blocking network round. first ('merge'|'replace') applies when this device never synced and a gist exists.
    -> (doc_to_adopt or None, new_base)."""
    if not gist.id:
        gist.find()
    remote = gist.load() if gist.id else None
    if base is None and remote is not None and first == "replace":
        return remote, digest(remote)
    up, adopt, new_base = decide(base, local, remote)
    if up is not None:
        gist.save(up)
    return adopt, new_base
