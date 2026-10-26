#!/usr/bin/env python3
"""Calder Coast multi-hop benchmark: Hashtag /search -> Matilda vs Gemini.

Phase 1 calls /search once per question and freezes the passages in results/search.json.
Phase 2 sends the identical frozen context to every model, 3 runs each, in a seeded random
order. Instructions + context go in the user message for every model (Matilda rejects the
system role). Rerunning skips (model, question, run) triples that already have an answer.

Usage: .venv/bin/python run_hop.py [--smoke]
Needs MATILDA_API_KEY, GOOGLE_API_KEY and HASHTAG_API_KEY (or hop_matilda2) in .env.
Optional: HOP_BASE_URL (Hashtag project) and HOP_RESULTS_DIR (default results/).
"""
from __future__ import annotations

import asyncio
import csv
import json
import os
import random
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE

HASHTAG_BASE = "https://kg-api-dev.hashtag.ai/anupam/hoppingmatilda"
GEMINI_URL = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
MODELS = ["matilda", "gemini-3.8-flash", "gemini-3.1-pro-preview"]
TOP_K = 20
RUNS = 3
SEED = 20261025
OUT = HERE / "results"
SEARCH_FILE = OUT / "search.json"
RUNS_FILE = OUT / "runs.jsonl"


# Hashtag's own answer prompt, used verbatim for every model.
SYSTEM_TEMPLATE = """You answer questions using only the documents in <context> and the conversation so far.

Rules:
- Base every statement on the context. If the context does not contain the answer, say so plainly (e.g. \"The provided documents don't cover this.\") and do not use outside knowledge.
- If the context only partly answers the question, give what it supports and state what is missing.
- Quote numbers, dates, amounts, names and legal terms exactly as written in the context.
- If documents disagree, present both versions and name their sources.
- Answer directly, without greetings or filler. Match the length to the question: one or two sentences for simple facts, structured detail (lists, steps) for complex ones.
- If the question is ambiguous, ask a short clarifying question.
- The context may start with a \"Database result\" block computed over the project's complete tables. Take counts, totals, sums, averages and lists from it exactly, say they describe records in this database, and when it shows only part of a list, give the full total. Never work out how many there are by counting passages. If the block says no exact result is available, do not state an exact number.

<context>
{context}
</context>"""


def load_env_file() -> None:
    p = ROOT / ".env"
    if not p.exists():
        return
    for line in p.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.removeprefix("export ").split("=", 1)
        os.environ.setdefault(k.strip(), v.strip().strip("\"'"))


async def matilda_call(client, system_prompt: str, question: str, retries: int = 3) -> dict:
    from matilda_client import QuotaExceededError
    from asyncio import TimeoutError
    start = time.monotonic()
    last_error = None
    attempt_errors = []
    for attempt in range(1, retries + 1):
        try:
            messages = ([{"role": "system", "content": system_prompt},
                         {"role": "user", "content": question}] if system_prompt else
                        [{"role": "user", "content": question}])
            r = await client.chat.create(messages=messages, incognito=True)
            usage = getattr(r, "usage", None)
            output_text = getattr(r, "output_text", "") or ""
            errors = getattr(r, "errors", None) or []
            return {"answer": output_text,
                    "output_tokens": getattr(usage, "output_tokens", None),
                    "input_tokens": getattr(usage, "input_tokens", None),
                    "context_messages_trimmed": getattr(usage, "context_messages_trimmed", None),
                    "errors": [str(e) for e in errors],
                    "truncated_reason": getattr(r, "truncated_reason", None),
                    "attempts": attempt, "attempt_errors": attempt_errors,
                    "latency_seconds": time.monotonic() - start}
        except (QuotaExceededError, TimeoutError) as e:
            last_error = f"{type(e).__name__}: {e}"
            attempt_errors.append({"attempt": attempt, "error": last_error})
            if attempt < retries:
                await asyncio.sleep(2 ** (attempt - 1))
        except Exception as e:
            # Retry explicit timeout-shaped SDK / transport errors only.
            if "timeout" in type(e).__name__.lower() and attempt < retries:
                last_error = f"{type(e).__name__}: {e}"
                attempt_errors.append({"attempt": attempt, "error": last_error})
                await asyncio.sleep(2 ** (attempt - 1))
            else:
                return {"answer": "", "output_tokens": None, "input_tokens": None,
                        "errors": [f"{type(e).__name__}: {e}"], "attempts": attempt,
                        "attempt_errors": attempt_errors,
                        "latency_seconds": time.monotonic() - start}
    return {"answer": "", "output_tokens": None, "input_tokens": None,
            "errors": [last_error or "retry limit reached"], "attempts": retries,
            "attempt_errors": attempt_errors,
            "latency_seconds": time.monotonic() - start}


def post_json(url: str, body: dict, headers: dict, timeout: int = 300) -> dict:
    req = urllib.request.Request(url, data=json.dumps(body).encode(), method="POST",
                                 headers={"content-type": "application/json", **headers})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read())


def load_questions() -> list[dict]:
    with (HERE / "questions.csv").open(newline="") as f:
        return list(csv.DictReader(f))


def load_supporting_docs() -> dict[str, list[str]]:
    # Read locally for retrieval recall only; never sent to any model or API.
    with (HERE / "answer_key - DO NOT UPLOAD.csv").open(newline="") as f:
        return {r["id"]: r["supporting_docs"].split(";") for r in csv.DictReader(f)}


def freeze_search(questions: list[dict]) -> dict:
    if SEARCH_FILE.exists():
        return json.loads(SEARCH_FILE.read_text())
    manifest = json.loads((HERE / "ingest_manifest.json").read_text())
    doc_num = {v["doc_id"]: k[:2] for k, v in manifest.items()}
    support = load_supporting_docs()
    key = os.environ.get("HASHTAG_API_KEY") or os.environ["hop_matilda2"]
    frozen = {}
    for q in questions:
        t0 = time.monotonic()
        r = post_json(f"{HASHTAG_BASE}/search", {"question": q["question"], "top_k": TOP_K},
                      {"x-api-key": key})
        passages = [{"rank": i, "doc": doc_num.get(x.get("doc_id"), "?"), "doc_id": x.get("doc_id"),
                     "score": x.get("score"), "text": x.get("text", "")}
                    for i, x in enumerate(r.get("results", []), 1)]
        found = {p["doc"] for p in passages}
        needed = support[q["id"]]
        frozen[q["id"]] = {
            "question": q["question"], "top_k": TOP_K, "latency_seconds": time.monotonic() - t0,
            "passages": passages,
            "supporting_docs": needed,
            "supporting_found": [d for d in needed if d in found],
            "recall": sum(d in found for d in needed) / len(needed),
        }
        print(f"search {q['id']}: {len(passages)} passages, recall {frozen[q['id']]['recall']:.2f}", flush=True)
    OUT.mkdir(parents=True, exist_ok=True)
    SEARCH_FILE.write_text(json.dumps(frozen, indent=2, ensure_ascii=False))
    return frozen


def build_prompt(entry: dict) -> tuple[str, int]:
    context = "\n\n".join(f"[Source {p['rank']}]\n{p['text']}" for p in entry["passages"])
    return SYSTEM_TEMPLATE.format(context=context) + "\n\nQuestion: " + entry["question"], len(context)


def gemini_call(model: str, prompt: str, retries: int = 3) -> dict:
    # Default generation settings: each model as shipped, no temperature or thinking overrides.
    start = time.monotonic()
    attempt_errors = []
    for attempt in range(1, retries + 1):
        try:
            r = post_json(GEMINI_URL.format(model=model),
                          {"contents": [{"role": "user", "parts": [{"text": prompt}]}]},
                          {"x-goog-api-key": os.environ["GOOGLE_API_KEY"]})
            cand = (r.get("candidates") or [{}])[0]
            parts = cand.get("content", {}).get("parts", [])
            usage = r.get("usageMetadata", {})
            return {"answer": "".join(p.get("text", "") for p in parts if not p.get("thought")),
                    "input_tokens": usage.get("promptTokenCount"),
                    "output_tokens": usage.get("candidatesTokenCount"),
                    "thinking_tokens": usage.get("thoughtsTokenCount"),
                    "finish_reason": cand.get("finishReason"),
                    "model_version": r.get("modelVersion"),
                    "errors": [] if cand.get("finishReason") in (None, "STOP") else [cand.get("finishReason")],
                    "attempts": attempt, "attempt_errors": attempt_errors,
                    "latency_seconds": time.monotonic() - start}
        except urllib.error.HTTPError as e:
            attempt_errors.append({"attempt": attempt, "error": f"HTTP {e.code}: {e.read().decode()[:200]}"})
            if e.code < 500 and e.code != 429:
                break
        except (TimeoutError, urllib.error.URLError) as e:
            attempt_errors.append({"attempt": attempt, "error": type(e).__name__})
        if attempt < retries:
            time.sleep(5 * 2 ** (attempt - 1))
    return {"answer": "", "errors": [attempt_errors[-1]["error"]], "attempts": len(attempt_errors),
            "attempt_errors": attempt_errors, "latency_seconds": time.monotonic() - start}


async def worker(model: str, jobs: list[dict], frozen: dict, client, out: Path) -> None:
    for job in jobs:
        prompt, ctx_chars = build_prompt(frozen[job["qid"]])
        started = datetime.now(timezone.utc).isoformat()
        if model == "matilda":
            res = await matilda_call(client, "", prompt)
        else:
            res = await asyncio.to_thread(gemini_call, model, prompt)
        line = {**job, "start_time": started, "context_chars": ctx_chars, **res}
        with out.open("a") as f:
            f.write(json.dumps(line, ensure_ascii=False) + "\n")
        status = "ERR " + str(res["errors"]) if not res["answer"] else f"{res['latency_seconds']:.1f}s"
        print(f"{model} {job['qid']} run {job['run']}: {status}", flush=True)


async def main() -> None:
    global HASHTAG_BASE, OUT, SEARCH_FILE, RUNS_FILE
    load_env_file()
    HASHTAG_BASE = os.environ.get("HOP_BASE_URL", HASHTAG_BASE)
    OUT = Path(os.environ.get("HOP_RESULTS_DIR", OUT))
    SEARCH_FILE, RUNS_FILE = OUT / "search.json", OUT / "runs.jsonl"
    smoke = "--smoke" in sys.argv
    questions = load_questions()
    frozen = freeze_search(questions)
    done = set()
    if RUNS_FILE.exists() and not smoke:
        for line in RUNS_FILE.read_text().splitlines():
            r = json.loads(line)
            if r.get("answer"):
                done.add((r["model"], r["qid"], r["run"]))
    jobs = [{"model": m, "qid": q["id"], "run": run}
            for q in questions for m in MODELS for run in range(1, RUNS + 1)]
    random.Random(SEED).shuffle(jobs)
    if smoke:
        jobs = [{"model": m, "qid": "Q03", "run": 0} for m in MODELS]
    jobs = [j for j in jobs if (j["model"], j["qid"], j["run"]) not in done]
    print(f"{len(jobs)} calls to make", flush=True)

    from matilda_client import MatildaClient
    async with MatildaClient(token=os.environ["MATILDA_API_KEY"]) as client:
        # One sequential worker per model, so latency is not inflated by self-contention.
        out = OUT / "smoke.jsonl" if smoke else RUNS_FILE
        await asyncio.gather(*(worker(m, [j for j in jobs if j["model"] == m], frozen, client, out)
                               for m in MODELS))


if __name__ == "__main__":
    asyncio.run(main())
