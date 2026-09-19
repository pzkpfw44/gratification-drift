# Gratification Drift

A paired-frame benchmark for how much a conversational model tells the user what the user wants to hear.

Every test is two chats with the same content. Frame A: the idea is a colleague's, the claim is a plain question, the decision is a friend's. Frame B: the same idea is the user's own, the same claim is one the user is sure of, the same decision is the user's and already judged right, or the user is upset, or keeps insisting. Gratification Drift is the movement from A to B in the user's favour, on five tests: praise calibration (T1), belief independence on settled facts (T2), accommodation of a distressed user (T3), validation versus agreement on borderline decisions (T4), and resistance under six turns of persistent pushback (T5). Two descriptive probes: lexical mirroring (D1) and memory retrieval (D2, app-only, by hand).

Paper: `paper/gratification_drift_v1.md` (Markdown source) and the PDF when released. Author: Alessio Biancheri, ignostiq (Alesserg Technology OÜ), Tallinn. Contact: a.biancheri@ignostiq.com.

## Run it by hand (twenty minutes)

Appendix C of the paper is a one-item-per-test scoring card. Open fresh chats, paste the prompts exactly, score with the rubric in `bench/rubric_v1.md`. No code needed.

## Run it at scale

Requires Python 3.10+, `pip install openai httpx`, and an OpenRouter key (or any OpenAI-compatible endpoint; change `BASE_URL` in `bench/gd_common.py`).

```
cd bench
set OPENROUTER_API_KEY=sk-or-...            # PowerShell: $env:OPENROUTER_API_KEY="sk-or-..."
python run_benchmark.py --models <model-id> --reps 5 --out responses.jsonl --budget 5
python judge.py --in responses.jsonl --out judged.jsonl --judges <judge-1> <judge-2> --cue-judges <judge-2> --max-calls 300 --workers 8
python judge.py --in responses.jsonl --out judged.jsonl --judges <judge-1> <judge-2> --cue-judges <judge-2> --budget 10 --workers 8
python analyze.py --responses responses.jsonl --judged judged.jsonl --judges <judge-1> <judge-2> --out results/
```

Collection and judging are resumable: re-running the same command only does the cells or judgements that are missing or failed. `--budget` is a hard stop in USD (per run for judging). `judge.py` prints each judge's price before starting and stops if a judge spends hidden reasoning tokens, which is what makes a judging run twenty times more expensive than planned. Pick judges from model families that are not under test.

## What is here

| Path | Content |
|---|---|
| `bench/items_v3.json` | The item bank: 8 idea pairs, 12 facts with wrong claims and reference answers, 12 decisions with pre-specified flaws, the pushback script, the mirroring conversations, the memory protocol. |
| `bench/rubric_v1.md` | Scoring rubric used by the judges and the human coder, and the drift formulas. |
| `bench/gd_common.py`, `run_benchmark.py`, `judge.py`, `analyze.py` | Collection, judging (two passes: scores and cue inventory), analysis (drift with bootstrap intervals over items, unfloored means and noise floor, judge agreement, cue emission table, blind coding pack). |
| `data/full_responses.jsonl` | All 3,476 model responses from the September 2026 run (six models, 3,351 usable conversations). |
| `data/full_judged.jsonl` | All judge outputs, including an abandoned first pass with a reasoning model (excluded from the analysis; kept for transparency). |
| `results/summary.md`, `summary.json` | Subscores, intervals, unfloored means, noise floor, per-model detail, cue emission table. |
| `results/cues.json` | Cue emission rates for all eleven cues, all models, all conditions. |
| `results/descriptives.txt`, `cue_compact.txt`, `d1_mirroring.txt` | The numbers behind the paper's tables. |
| `results/coding_pack.md`, `coding_key.json`, `human_coding_scores.csv`, `human_check_kappa.json` | The 60-transcript blind human check: the pack as coded, the key (model per transcript), the coder's scores, and the agreement statistics. |
| `paper/` | The paper source. |

The two data files are large (10 MB and 6 MB) and are added to the repository separately; if they are missing, they are being uploaded.

## Models in the September 2026 run

anthropic/claude-sonnet-5, openai/gpt-5.6-luna, google/gemini-3.8-flash, deepseek/deepseek-v3.2, meta-llama/llama-4-maverick, qwen/qwen3-max, as served by OpenRouter on 13 to 17 September 2026, provider default temperature, no system prompt. Judges: mistralai/mistral-medium-3-5 and moonshotai/kimi-k2-0905 (scores), moonshotai/kimi-k2-0905 (cue inventory). Results are a snapshot of those versions.

## Licence

Code (`bench/*.py`): MIT. Items, rubric, data, results and paper: CC BY 4.0. If you use the benchmark, cite the paper.
