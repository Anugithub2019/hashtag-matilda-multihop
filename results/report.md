# Calder Coast multi-hop benchmark: Matilda vs Gemini on Hashtag search

Run date: 2026-10-25. Corpus: `anupam/hoppingmatilda` (38 prose documents, one chunk each).
Seed: 20261025. 26 questions × 3 models × 3 runs = 234 calls; all returned an answer, and no API
errors or truncation flags were reported.

## Setup

- `/search` was called **once per question** (`top_k` 20) and the passages were frozen in
  `search.json`. Every model saw the identical context, in the same order.
- The same Hashtag answer prompt was used for every model, with instructions and context in the
  **user** message, because Matilda rejects the `system` role. Each model ran with its default
  settings.
- Models: Matilda (server-chosen model), `gemini-3.8-flash`, `gemini-3.1-pro-preview`.

## Retrieval

The search results contained every needed document for 25 of 26 questions. Q24 missed doc 05,
the rename press release, but docs 04 and 18 were enough to answer it. With 20 of 38 documents
returned, each prompt held about half the corpus (median 15,200 characters). **This run therefore
tests multi-hop reasoning over a shared context, not retrieval.**

## Accuracy

Factual questions are Q01–Q16 and Q20–Q26 (23 questions × 3 runs = 69 answers). The decline or
clarify questions are Q17 (false premise), Q18 (unanswerable) and Q19 (ambiguous), 9 answers per model.

| Model | Factual pass | Factual partial | Fail | Decline/clarify pass | Partial |
|---|---:|---:|---:|---:|---:|
| Matilda | 67 / 69 | 2 | 0 | 7 / 9 | 2 |
| Gemini 3.8 Flash | 69 / 69 | 0 | 0 | 9 / 9 | 0 |
| Gemini 3.1 Pro Preview | 69 / 69 | 0 | 0 | 9 / 9 | 0 |

No model fell for any distractor (Tidewell Seafoods, Brightline Logistics, Dr Osei-Mensah,
Harry Okafor, Copper Kettle, Greywater Maritime Insurance). Every model resolved the rename,
the maiden name, the description-only links and the temporal question (Q14) in all 3 runs.

### Where the models differed

| Question | Matilda | Gemini Flash | Gemini Pro |
|---|---|---|---|
| Q16 contradiction (two dates for the fire) | 2/3 pass. Run 2 gave only "winter of 2020" and missed the conflict. | 3/3 present both sources | 3/3 present both sources |
| Q19 ambiguous "Tidewell" | 1/3 pass. Runs 2–3 named only Tidewell Bio's CEO. | 3/3 (two asked which one, one named both) | 3/3 asked which one |
| Q20 comparison | 2/3 pass. Run 3 opened with the wrong company, then gave the right dates and the right conclusion. | 3/3 | 3/3 |

Gemini Pro flagged twice (Q20 runs 1 and 3) that the documents never use the term "Series B".
That is correct: the question uses a label the corpus doesn't contain. The answer was still right.

### Answer quality issue

**4 of 78 Matilda answers stop mid-sentence** (Q06 run 1, Q14 run 2, Q21 runs 1 and 3, for
example "…in his laboratory in 201"). The SDK reported no truncation. Each still contained the
required facts, so they score as pass, but a user would see a broken sentence. No Gemini answer
was cut off.

## Latency and tokens

| Model | Median latency | Range | Input tokens | Thinking tokens | Output tokens |
|---|---:|---:|---:|---:|---:|
| Matilda | 2.1 s | 1.6–3.8 s | not reported by SDK | — | 4,691 |
| Gemini 3.8 Flash | 4.9 s | 2.5–48.2 s | 298,416 | 27,153 | 3,686 |
| Gemini 3.1 Pro Preview | 5.7 s | 4.0–10.1 s | 298,416 | 42,982 | 3,201 |

Latency is the model call only; `/search` added a median 0.84 s per question, the same for all models.
The Gemini models spend most of their tokens on hidden reasoning ("thinking"): about 7–13 thinking
tokens per answer token.

### Cost

At Google's published rates (26 Oct 2026), the 78 Gemini 3.8 Flash answers cost **$0.34**
($0.75 / $3.75 per 1M input / output tokens, introductory pricing). The 78 Gemini 3.1 Pro Preview
answers cost **$1.15** ($2 / $12). Thinking tokens are billed as output and made up 88% (Flash)
and 93% (Pro) of output tokens. Matilda's cost cannot be calculated: the SDK doesn't report
input tokens and no per-token price is published.

## Conclusions

1. Given the same Hashtag passages, **all three models answer multi-hop questions almost
   perfectly** on this corpus. Matilda's gap is small (2 partials out of 69) and lies in edge
   behaviour, not in following links between documents.
2. Matilda is **2–3× faster** and uses no reasoning tokens. Its weak spots are noticing
   contradictions and ambiguity, which the prompt explicitly asks for, and answers that stop
   mid-sentence.
3. Because search returned almost everything, this result **does not yet measure the knowledge
   graph**. Rerunning with `top_k` 5–8 would make the search the bottleneck, so differences
   would show how well Hashtag's search follows links between documents.

## Limitations

The sample is 26 questions × 3 runs on a small synthetic corpus. Matilda's model is chosen by the
server and may change. Gemini 3.1 Pro is a preview model. One person (Claude) scored the answers
against the answer key, with a reason recorded for each in `scores.csv`.

## Files

`search.json` (frozen passages and recall), `runs.jsonl` (every call), `scores.csv` (score and
reason per answer), `smoke.jsonl` (pre-run check, not scored).
