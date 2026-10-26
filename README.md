# Calder Coast: multi-hop RAG with Hashtag AI, Matilda and Gemini

This experiment tests how well an LLM answers **multi-hop questions** when its evidence comes
from the **Hashtag AI knowledge-graph search API**. It compares **Matilda**, Maincode's
Australian model, with Google's **Gemini 3.8 Flash** and **Gemini 3.1 Pro Preview**.

Every model gets the *same* Hashtag search results and the *same* prompt, so differences come
from the model alone.

## The dataset

38 short, fully fictional documents (about 4,600 words) set in an invented region, the
"Calder Coast". They are news articles, press releases, a podcast transcript, newsletters, an
investor letter and profiles: **prose only, with no tables, IDs or structured fields**. Every link
between documents has to be inferred from meaning:

- **Renames:** Tidewell Bio becomes Halcyon Therapeutics. Older and newer documents use different names.
- **Descriptions instead of names:** "her husband, an infectious-diseases physician at St Brigid's".
- **Maiden names:** only one document says Imogen Varga was born Fenwick.
- **Dates:** "who was CEO when the cyclone hit?" needs start and end dates from two documents.
- **Look-alike distractors:** Tidewell Seafoods, Brightline Logistics, Dr Samuel Osei-Mensah,
  Harry Okafor, the Copper Kettle, Greywater Maritime Insurance.
- **A planted contradiction**, a **false premise**, an **unanswerable** question and an **ambiguous** one.

There are 26 questions: 2 single-hop controls, 2–5-hop bridges, temporal, comparison,
aggregation, contradiction, and three the model should decline or ask about.

## Method

1. Each document was ingested into Hashtag project `anupam/hoppingmatilda` through `/process`
   as plain text (`ingest.py`). The stored text was checked against every source file.
2. `/search` was called **once per question** (`top_k` 20) and the passages were frozen
   (`results/search.json`).
3. Each model received Hashtag's own answer prompt plus the frozen passages in the **user**
   message (Matilda rejects the `system` role, so all models were treated the same way). Each
   model ran with its default settings.
4. Each question ran 3 times per model in a seeded random order: 234 calls in total.
5. Every answer was scored against the answer key as pass, partial or fail, with a written reason.

## Results

| | Matilda | Gemini 3.8 Flash | Gemini 3.1 Pro Preview |
|---|---:|---:|---:|
| Factual questions (69 answers) | 67 pass, 2 partial | 69 pass | 69 pass |
| Decline / clarify (9 answers) | 7 pass, 2 partial | 9 pass | 9 pass |
| Fails | 0 | 0 | 0 |
| Median latency (model call) | **2.1 s** | 4.9 s | 5.7 s |
| Answers cut off mid-sentence | 4 of 78 | 0 | 0 |

- **No model fell for a distractor**, and all three resolved the renames, the maiden name, the
  description-only links and the temporal question in every run.
- Matilda's partials were edge behaviour: it missed the ambiguity in "Tidewell" (2 runs) and the
  contradiction between two dates (1 run), and one comparison answer opened with the wrong
  company before reaching the right conclusion.
- Hashtag `/search` took a median **0.84 s** per question.
- **Caveat:** with `top_k` 20 on a 38-document corpus, search returned every needed document for
  25 of 26 questions. This run measures how well the models reason from Hashtag's evidence. It
  does not stress the search itself. A lower `top_k` is the next experiment.

Full write-up: [`results/report.md`](results/report.md).

## Cost

Token counts come from each API's own usage report. Prices are Google's published Gemini API
rates, checked on 26 October 2026.

| Model | Input tokens | Thinking tokens | Answer tokens | Price (per 1M in / out) | Cost, 78 answers | Per answer |
|---|---:|---:|---:|---|---:|---:|
| Gemini 3.8 Flash | 298,416 | 27,153 | 3,686 | $0.75 / $3.75 (introductory, to 31 Dec 2026) | **$0.34** | $0.004 |
| Gemini 3.1 Pro Preview | 298,416 | 42,982 | 3,201 | $2 / $12 (prompts under 200k) | **$1.15** | $0.015 |
| Matilda | not reported | none | 4,691 | not published | **cannot be calculated** | — |

Gemini bills thinking tokens as output. They were **88% (Flash) and 93% (Pro)** of all output
tokens, so most of Gemini's output cost is reasoning the user never sees.

**What we could not get for Matilda:**
- **Input tokens:** the SDK (`matilda-client` 0.4.0) returns only output tokens.
- **Price:** we found no published per-token rate for Matilda's API, so no dollar cost can be given.
- **Model identity:** there is no model parameter, the server chooses the model, and the response doesn't name it.
- **Settings:** temperature and other sampling settings can't be set.
- **System role:** it is rejected, so the instructions go in the user message.
- **Truncation signal:** 4 answers stopped mid-sentence while the SDK reported no truncation.

**Hashtag's cost** isn't included: ingestion uses project credits, and `/search` doesn't return token or credit usage.

## Files

| Path | What it is |
|---|---|
| `corpus/` | The 38 documents uploaded to Hashtag |
| `questions.csv` | The 26 questions sent to search and the models |
| `answer_key - DO NOT UPLOAD.csv` | Expected answers, hop chains, supporting documents, scoring notes. Never sent to any API. |
| `ingest.py`, `ingest_manifest.json` | Ingestion script and the file → Hashtag `doc_id` map |
| `run_hop.py` | Freezes the search results, then runs all models |
| `results/` | `search.json`, `runs.jsonl`, `scores.csv`, `report.md` |

## Reproduce

Setup (Python 3.12+):

```bash
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
cp .env.example .env    # then add MATILDA_API_KEY, GOOGLE_API_KEY, HASHTAG_API_KEY
```

**A. Rerun the models on our exact search results.** No Hashtag account is needed. Every model
gets byte-for-byte the passages used here:

```bash
mkdir -p reruns/mine && cp results/search.json reruns/mine/
HOP_RESULTS_DIR=reruns/mine .venv/bin/python run_hop.py --smoke   # 3 calls, quick check
HOP_RESULTS_DIR=reruns/mine .venv/bin/python run_hop.py           # full 234 calls
```

**B. Rerun everything, including ingestion and search, in your own Hashtag project:**

```bash
export HOP_BASE_URL=https://kg-api-dev.hashtag.ai/<user>/<empty-project>
.venv/bin/python ingest.py                                  # uploads corpus/ and updates the manifest
HOP_RESULTS_DIR=reruns/full .venv/bin/python run_hop.py     # searches fresh, then runs all models
```

`run_hop.py` resumes if interrupted: it skips any (model, question, run) that already has an
answer in the results folder. Scoring was done by hand against the answer key, with a reason for
every score in `results/scores.csv`; score a rerun the same way.

**Expect small differences on a rerun.** Matilda's server-side model and both models' sampling
aren't fixed. Fresh Hashtag search results may also differ from `results/search.json` if the
service changes.

**Contamination note:** the answer key is public in this repo. Future models may have seen it,
so for a clean test of a new model, write new questions.

## Limitations

The sample is small: 26 questions × 3 runs on one synthetic corpus. Matilda's model is chosen by
the server and may change. Gemini 3.1 Pro is a preview model. Gemini prices are introductory
and will change. The answers were scored by one reviewer (Claude) against the answer key.
