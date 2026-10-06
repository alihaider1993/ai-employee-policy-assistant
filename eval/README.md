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
- **Cited page numbers are one too low.** The generator passes the index's 0-based page to the model and returns it in `sources`, so citations and `/ask` sources are off by one.
- **Duplicate chunks waste about one slot in three.** At k=3 the chunks cover 2.00 distinct pages on average, because several chunks often come from the same page.
- **Not-covered questions still get chunks.** Pure vector search always returns k results, so refusing depends entirely on the generation prompt.

## Known limits

- **The judge is the bot's model.** It is the same Azure OpenAI deployment as the bot, so it can share the bot's blind spots.
- **The judge isn't fully reliable.** It sometimes marks an omission as unfaithful. When the bot refuses, it sometimes returns `faithful: null` or an empty facts list, and those questions end up as `error` (q05).
- **Answers vary between runs**, even with the same retrieved chunks. Use `--repeat` and read results per question rather than from a single run.
- **21 questions is a small set.** One question changes a policy pass rate by about 9 points.
