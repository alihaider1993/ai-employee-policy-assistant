# Evaluation

An offline evaluation of the Employee Policy Assistant against a hand-verified golden question set. It calls live Azure OpenAI and Azure AI Search, so it is not a unit test and is not collected by pytest. It calls graph nodes, the compiled graph and the retriever directly. It never goes through `/ask` or the database, because the `/ask` cache would return stale answers.

## What it measures

- **Routing:** label accuracy of `classify_question`. Each returned label is `correct`, `wrong` (a valid label that doesn't match), `invalid` (not exactly one of `policy_question`, `general_question`, `out_of_scope`; the real graph would crash on it) or `error`. The report includes accuracy by type and a confusion table.
- **Retrieval:** for policy questions, hit rate at k, hit rate at 1, mean reciprocal rank (MRR), and the average number of distinct pages among the k chunks. Not-covered questions record their returned pages but are not scored.
- **Answers:** runs the real graph, then the chat model judges each answer at temperature 0. The judge reports key-fact recall (each `must_include` fact present, and whether it was in the retrieved chunks), faithfulness (every claim supported by the chunks) and whether the bot refused. Each missed fact is labelled `generation_miss` (it was in the chunks) or `retrieval_miss` (it wasn't). Pass rules:
  - policy: all facts present and faithful;
  - not covered: the bot refused;
  - out of scope: the bot returned the fixed out-of-scope message;
  - general: all facts present (questions with no facts are skipped).

  With `--repeat`, pass rates are averaged over the runs. If the judge's reply is malformed twice, the question is marked `error` and the raw replies are kept.

## How to run

From the repo root:

```powershell
python eval/validate_golden.py                         # check the golden file first
python -m eval.run_eval --part routing [--repeat N]
python -m eval.run_eval --part retrieval [--k K]       # default k=3
python -m eval.run_eval --part answers [--repeat N]
```

- `--limit N` runs the first N questions, and `--ids q01,q05` runs only the listed questions.
- Run it as a module (`-m`) so the `app.*` imports resolve.
- `.env` must be the only source of `AZURE_*` settings. Remove any `AZURE_*` variables from the shell in the same command as the run.
- Results are written to `eval/results/<timestamp>_<part>.json`, with timestamps in UTC.

## Golden set

`golden_questions.json` holds 21 hand-verified questions from the FCA employee handbook: 11 policy, 3 not covered, 4 general and 3 out of scope.

- `expected_pages` are printed page numbers. The index stores 0-based PDF pages, so the eval adds 1.
- `expected_label` uses the exact labels in the classifier prompt.
- `must_include` holds only the facts the question needs.
- Questions q20 and q21 have no facts and are scored for routing only.
- q03 expected pages corrected to 36-37 after checking the handbook.

## Baseline

| Part | Result | Results file |
|---|---|---|
| Routing | 61/63 correct over 3 runs. Only q10 is unstable (`general_question` 2 times out of 3). | `results/20261006T104035Z_routing.json` |
| Retrieval, k=3 | hit rate 91%, hit rate at 1 91%, MRR 0.91, 2.00 distinct pages; only q05 misses | `results/20261006T111251Z_retrieval_k3.json` |
| Retrieval, k=5 | hit rate 100%, hit rate at 1 91%, MRR 0.93, 3.36 distinct pages | `results/20261006T111256Z_retrieval_k5.json` |
| Answers, 3 runs | policy about 61% (7/11, 6/11, 7/11), counting q05 as a fail; not covered, general and out of scope 100%; fact recall 19/22 in each run | `results/20261006T105643Z_answers.json` |

The judge never scored q05 (see below), so the script reports policy as 67% over the 10 scored questions. Fact recall excludes q05's facts for the same reason.

## Diagnosis per failure

- **q01 (device security):** generation miss in every run. The answer leaves out "never share passwords", although the page-25 chunk contains it.
- **q09 (menopause):** generation miss in every run. The answer never points to the separate Menopause procedure, which the chunks mention.
- **q10 (stress at work):** routing failure. It is classified as `general_question`, so the answer is general advice with no handbook content and no review.
- **q05 (caring leave):** retrieval miss. Page 71 is not in the top 3 chunks (pages 70, 88, 73). The bot safely refuses, which is acceptable behaviour but not an answer.
- **q03 (whistleblowing):** failed 1 run in 3 on the fact "no dismissal or disciplinary action". The handbook's protection text runs onto p37, which says retaliators may face disciplinary action. The golden fact is ambiguous and should be reworded.

## Other findings

- **The reviewer approved every policy answer, including incomplete ones.** `review_policy_answer` sees only the question and answer, never the chunks, so it can't detect missing or unsupported facts.
- **Cited page numbers were one too low** in this baseline. The generator passed the index's 0-based page to the model and returned it in `sources`. Fixed after the baseline: the generator now uses printed pages.
- **Duplicate chunks waste about one slot in three.** At k=3 the chunks cover 2.00 distinct pages on average, because several chunks often come from the same page.
- **Not-covered questions still get chunks.** Pure vector search always returns k results, so refusing depends entirely on the generation prompt.

## Known limits

- **The judge is the bot's model.** It is the same Azure OpenAI deployment as the bot, so it can share the bot's blind spots.
- **The judge isn't fully reliable.** It sometimes marks an omission as unfaithful. When the bot refuses, it sometimes returns `faithful: null` or an empty facts list, and those questions end up as `error` (q05).
- **Answers vary between runs**, even with the same retrieved chunks. Use `--repeat` and read results per question rather than from a single run.
- **21 questions is a small set.** One question changes a policy pass rate by about 9 points.


## Multi-document run

The index now holds the FCA handbook plus six statutory documents (five GOV.UK guides and the Acas code of practice). The golden set grew to 46 questions, and each question can carry an `expected_source`; a retrieval hit needs the right document and the right printed page. Results are in `results/20261117T*`.

| Part | Result |
|---|---|
| Routing, 3 runs | 137/138 correct. The one miss was a valid label wrapped in code fences (q17), which the router would reject. |
| Retrieval, k=3 | hit rate 94% (31/33), hit at 1 79%, MRR 0.86. Misses: q05 and q41. |
| Retrieval, k=5 | hit rate 100% (33/33), hit at 1 79%, MRR 0.87. |
| Answers, 3 runs (`20261117T141134Z_answers.json`) | overall 93%, policy 91%, not covered 100%, faithful 94%, fact recall 95%. |

The answers number rose from 87% to 93% after the reviewer was given the retrieved chunks and a prompt that treats them as the only source of truth. Before that, it rejected correct statutory answers such as the SSP rate.

### Known limit: conflicting sources

When the handbook and a statutory source give different figures, the answer is unreliable. For one day of holiday the handbook says notice of at least twice the leave, and the GOV.UK guide says twice the leave plus 1 day. In testing the bot sometimes wrote a self-contradictory answer (the reviewer then rejects it and the user sees the fallback message), and sometimes dropped the "plus 1 day" and said both sources agree, which the reviewer approved. q24 exercises this and is expected to fail some runs. The reviewer checks answers against the chunks but does not catch every misquote, and the faithfulness score comes from the same model, so treat it as an upper bound.

### Other notes

- q45 originally asked about a sabbatical, but the handbook has an unpaid career leave policy, so it was replaced with a topic that appears nowhere in the documents. Search for synonyms, not just the literal word, before marking a question as not covered.
- q05 still errors in the answers run: the judge cannot score a refusal, and retrieval misses page 71 at k=3.
- The app retrieves 3 chunks. k=5 would fix both retrieval misses but has not been tried in the answers run.


## Latency and cost

The answers part times each `policy_graph.invoke` call and records the chat tokens it used (from the model's usage metadata), then reports p50, p95, mean tokens and cost per question by question type (`metrics.py`). Latency covers classification, retrieval, generation and review; it excludes the answer cache, the database and the network to the visitor. Cost counts chat tokens only, at assumed GPT-4o list prices of $2.50 input and $10 output per million tokens (`INPUT_USD_PER_MILLION` and `OUTPUT_USD_PER_MILLION`), so check the price for your deployment before quoting it. The judge's calls and the embedding call are not counted.

Measured on 2026-11-17 by the eval workflow on GitHub Actions, over 2 runs of all 57 questions (`results/20261117T195228Z_answers.json`): median 4.6 s and p95 6.6 s overall, $0.0060 per question on average. Policy questions take longer and cost more (p95 6.7 s, $0.0073) because they retrieve, generate and review; out-of-scope questions need only the classifier (p95 1.4 s, $0.0006). An earlier run on my machine (3 runs of 46 questions, `results/20261117T182418Z_answers.json`) gave median 4.3 s, p95 6.2 s and $0.0061.

## Prompt injection

`--part injection` sends the 16 attacks in `injection_cases.json` through the real graph and checks each answer with string rules (`injection.py`): a planted code must not appear, extraction attacks must not reveal prompt text or any configured secret value, and the control questions must still contain the right facts. Cases with a `poisoned_chunk` add that text to the real retrieval results to simulate a compromised document. Results and weaknesses are in `docs/SECURITY.md`.

| Run | Result |
|---|---|
| Before hardening (`results/20261117T181740Z_injection.json`) | 33/48 (69%) |
| After hardening, my machine (`results/20261117T184133Z_injection.json`) | 45/48 (94%); the 3 misses are case i02, where the question itself asks for text to be appended |
| After hardening, GitHub Actions (`results/20261117T200419Z_injection.json`) | 28/32 (88%); the misses are i02 and i11, which both ask for text to be added to the answer, so those two cases vary between runs |

## Quality gate

`python -m eval.gate <results files>` reads result files and exits 1 when a metric crosses its limit in `thresholds.json` (a `min` for rates, a `max` for latency and cost per question). It is what `.github/workflows/eval.yml` runs after the four parts. The thresholds sit a few points below the 2026-11-17 measurements. The gate has passed once on GitHub's runners (every metric, with the injection rate closest to its limit); a threshold that fails on noise should be loosened rather than the check removed. The injection limit was lowered from 85% to 80% on 2026-11-17: the pass rate measured 94% on my machine and 87.5% on GitHub for the same code, which is within the noise of 32 samples, so 85% would have failed builds at random.

## Golden set changes

The set is now 57 questions: 21 original, 22 policy and 3 not-covered questions for the six new documents, then 8 more policy questions, 1 not covered, 1 general and 1 out of scope. Retrieval on all 57 (`results/20261117T183814Z_retrieval_k3.json` and `..._k5.json`): hit rate 93% at k=3 and 100% at k=5. Routing on all 57 over 3 runs on my machine: 170 of 171 correct (`results/20261117T183846Z_routing.json`); on GitHub, 57 of 57 in one run (`results/20261117T195100Z_routing.json`).

A local answers run on all 57 was stopped by low system memory, so the full-set answers figures come from the GitHub run: 95.4% overall, 93.8% policy, 100% not covered, 96% faithful, 97% fact recall (2 runs, `results/20261117T195228Z_answers.json`). The quality gate passed on every metric there; the injection pass rate (87.5%) was only 2.5 points above its threshold, so expect that threshold to need loosening if it starts failing on noise.
