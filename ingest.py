"""Ingest corpus/*.txt into a Hashtag project via /process and write ingest_manifest.json.

Usage: python3 ingest.py  (reads HASHTAG_API_KEY or hop_matilda2, and HOP_BASE_URL, from .env or the environment)
Files already ingested into the same project (per the manifest) are skipped, so it is safe to rerun.
"""
import json, os, pathlib, time, urllib.error, urllib.request

HERE = pathlib.Path(__file__).parent
for line in (HERE / ".env").read_text().splitlines():
    if "=" in line and not line.lstrip().startswith("#"):
        k, v = line.split("=", 1)
        os.environ.setdefault(k.strip(), v.strip().strip("\"'"))
KEY = os.environ.get("HASHTAG_API_KEY") or os.environ["hop_matilda2"]
BASE = os.environ.get("HOP_BASE_URL", "https://kg-api-dev.hashtag.ai/anupam/hoppingmatilda")
MANIFEST = HERE / "ingest_manifest.json"


def post(path, body):
    req = urllib.request.Request(BASE + path, data=json.dumps(body).encode(), method="POST",
                                 headers={"x-api-key": KEY, "content-type": "application/json"})
    with urllib.request.urlopen(req, timeout=600) as r:
        return json.loads(r.read())


manifest = json.loads(MANIFEST.read_text()) if MANIFEST.exists() else {}
for p in sorted((HERE / "corpus").glob("*.txt")):
    done = manifest.get(p.name, {})
    if done.get("status") == "Success" and done.get("base") == BASE:
        continue
    # type "text" stores `url` verbatim, so send the text itself (a data: URL would be stored as base64).
    url = p.read_text()
    for attempt in range(3):
        try:
            r = post("/process", {"type": "text", "url": url})
            manifest[p.name] = {"base": BASE, "doc_id": r["doc_id"], **r["info"]}
            break
        except (urllib.error.URLError, TimeoutError) as e:
            detail = e.read().decode()[:300] if isinstance(e, urllib.error.HTTPError) else str(e)
            manifest[p.name] = {"status": "Error", "error": detail}
            time.sleep(5 * (attempt + 1))
    print(p.name, manifest[p.name].get("status"), manifest[p.name].get("total_chunks_generated"), flush=True)
    MANIFEST.write_text(json.dumps(manifest, indent=2))
