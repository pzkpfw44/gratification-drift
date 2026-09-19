# Gratification Drift benchmark, scripts v3.4

Files: gd_common.py, run_benchmark.py, judge.py, analyze.py, items_v3.json, rubric_v1.md.

## Judging (v3.4)
- Prints each judge's price before starting; refuses unknown ids.
- Stops if a judge shows the hidden-reasoning pattern (3+ calls and >10% of its calls).
- --max-calls N runs a chunk; --budget is USD for THIS RUN; --cue-judges lets the cue pass use fewer judges.
- Re-run the same command after rate-limit (429) errors; only failed judgements are redone.

Chunk:
    python judge.py --in full_responses.jsonl --out full_judged.jsonl --judges mistralai/mistral-medium-3-5 moonshotai/kimi-k2-0905 --cue-judges moonshotai/kimi-k2-0905 --max-calls 300 --workers 8
Full:
    python judge.py --in full_responses.jsonl --out full_judged.jsonl --judges mistralai/mistral-medium-3-5 moonshotai/kimi-k2-0905 --cue-judges moonshotai/kimi-k2-0905 --budget 14 --workers 8

## Analysis (restrict to the final judges)
    python analyze.py --responses full_responses.jsonl --judged full_judged.jsonl --judges mistralai/mistral-medium-3-5 moonshotai/kimi-k2-0905 --out results/
