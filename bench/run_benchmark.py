#!/usr/bin/env python3
"""Gratification Drift benchmark: data collection.

Usage:
  export OPENROUTER_API_KEY=sk-or-...
  python run_benchmark.py --pilot                 # 3 models, 2 reps, one paraphrase
  python run_benchmark.py --reps 5                # full item bank, auto-picked models
  python run_benchmark.py --models anthropic/claude-sonnet-4.5 openai/gpt-5.1 --reps 3
  python run_benchmark.py --list-models           # show what would be picked, then exit

Output: responses.jsonl (one record per API call; safe to re-run, completed cells are skipped).
"""
import argparse, json, random, sys, time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from gd_common import client, pick_models, credits, chat, cell_id, load_jsonl, append_jsonl, rec_cost, spent_so_far, is_truncated, latest_good

HERE = Path(__file__).parent
ITEMS = json.loads((HERE / "items_v3.json").read_text(encoding="utf-8"))


def build_cells(reps, paraphrases, t3_variants):
    cells = []
    # T1 praise: each idea (strong/weak) in frame A and B
    t = ITEMS["T1_praise"]
    for p in t["pairs"]:
        for quality in ("strong", "weak"):
            for frame in ("A", "B"):
                prompt = t["frame_" + frame].format(idea=p[quality])
                for r in range(reps):
                    cells.append(dict(test="T1", item=p["id"], quality=quality, frame=frame, para=0, rep=r, messages=[{"role": "user", "content": prompt}]))
    # T2 facts
    t = ITEMS["T2_facts"]
    for it in t["items"]:
        for r in range(reps):
            cells.append(dict(test="T2", item=it["id"], frame="A", para=0, rep=r, messages=[{"role": "user", "content": t["frame_A"].format(**it)}]))
            cells.append(dict(test="T2", item=it["id"], frame="B", para=0, rep=r, messages=[{"role": "user", "content": t["frame_B"].format(**it)}]))
            if paraphrases > 1:
                cells.append(dict(test="T2", item=it["id"], frame="B", para=1, rep=r, messages=[{"role": "user", "content": t["frame_B_paraphrase"].format(**it)[0].upper() + t["frame_B_paraphrase"].format(**it)[1:]}]))
    # T3 vulnerability: frame A = neutral wrong belief (same as T2 frame B, reused, not re-run); frame B variants
    t = ITEMS["T3_vulnerability"]
    for it in ITEMS["T2_facts"]["items"]:
        for r in range(reps):
            for v in t3_variants:
                key = "frame_B_" + v
                cells.append(dict(test="T3", item=it["id"], frame="B", variant=v, para=0, rep=r, messages=[{"role": "user", "content": t[key].format(**it)}]))
    # T4 decisions
    t = ITEMS["T4_decisions"]
    for it in t["items"]:
        for r in range(reps):
            cells.append(dict(test="T4", item=it["id"], frame="A", para=0, rep=r, messages=[{"role": "user", "content": t["frame_A"].format(**it)}]))
            cells.append(dict(test="T4", item=it["id"], frame="B", para=0, rep=r, messages=[{"role": "user", "content": t["frame_B"].format(**it)}]))
            if paraphrases > 1:
                cells.append(dict(test="T4", item=it["id"], frame="B", para=1, rep=r, messages=[{"role": "user", "content": t["frame_B_paraphrase"].format(**it)}]))
    # T5 pushback: multi-turn, handled separately (one cell = whole conversation)
    t = ITEMS["T5_pushback"]
    facts = {f["id"]: f for f in ITEMS["T2_facts"]["items"]}
    for fid in t["uses_items"]:
        for r in range(reps):
            cells.append(dict(test="T5", item=fid, frame="multi", para=0, rep=r, wrong_claim=facts[fid]["wrong_claim"]))
    # D1 mirroring: two 5-turn conversations
    t = ITEMS["D1_mirroring"]
    for cond in ("neutral", "distinctive"):
        for r in range(reps):
            cells.append(dict(test="D1", item="mirror", frame=cond, para=0, rep=r, turns=t[cond + "_turns"]))
    return cells


def run_cell(c, model, cell, temperature):
    rec = dict(cell, model=model, ts=time.time())
    if cell["test"] == "T5":
        t = ITEMS["T5_pushback"]
        msgs = [{"role": "user", "content": t["turn1"].format(wrong_claim=cell["wrong_claim"])}]
        turns = []
        for k, pb in enumerate([None] + t["pushback"]):
            if pb is not None:
                msgs.append({"role": "user", "content": pb.format(wrong_claim=cell["wrong_claim"])})
            txt, usage, err = chat(c, model, msgs, temperature)
            turns.append(dict(turn=k + 1, user=msgs[-1]["content"], assistant=txt, usage=usage, error=err))
            if err:
                break
            msgs.append({"role": "assistant", "content": txt})
        rec["turns"] = turns
        rec["error"] = turns[-1]["error"]
    elif cell["test"] == "D1":
        msgs, turns = [], []
        for k, u in enumerate(cell["turns"]):
            msgs.append({"role": "user", "content": u})
            txt, usage, err = chat(c, model, msgs, temperature)
            turns.append(dict(turn=k + 1, user=u, assistant=txt, usage=usage, error=err))
            if err:
                break
            msgs.append({"role": "assistant", "content": txt})
        rec["turns"] = turns
        rec["error"] = turns[-1]["error"]
        rec.pop("turns_in", None)
    else:
        txt, usage, err = chat(c, model, cell["messages"], temperature)
        rec.update(assistant=txt, usage=usage, error=err)
    return rec


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--pilot", action="store_true")
    ap.add_argument("--models", nargs="*")
    ap.add_argument("--families", nargs="*", help="subset of: claude gpt gemini deepseek llama qwen")
    ap.add_argument("--reps", type=int, default=5)
    ap.add_argument("--paraphrases", type=int, default=1)
    ap.add_argument("--t3-variants", nargs="*", default=["distress_confident", "sad_only"])
    ap.add_argument("--temperature", type=float, default=None, help="default: provider default")
    ap.add_argument("--workers", type=int, default=4)
    ap.add_argument("--out", default="responses.jsonl")
    ap.add_argument("--list-models", action="store_true")
    ap.add_argument("--show-family", help="print every OpenRouter model id containing this string (e.g. gemini) and exit")
    ap.add_argument("--only-tests", nargs="*", help="e.g. T2 T3")
    ap.add_argument("--budget", type=float, default=None, help="stop submitting new calls once this many USD have been spent in this output file (checked continuously)")
    a = ap.parse_args()

    c = client()
    if a.list_models:
        pick_models(c); return
    if a.show_family:
        from gd_common import list_models
        for m in sorted(list_models(c), key=lambda m: -m.get("created", 0)):
            if a.show_family.lower() in m["id"].lower():
                print(m["id"])
        return
    if a.pilot:
        a.reps, a.paraphrases, a.t3_variants = 2, 1, ["distress_confident"]
        fams = a.families or ["claude", "gpt", "deepseek"]
    else:
        fams = a.families
    models = a.models or list(pick_models(c, fams).values())
    if not models:
        sys.exit("No models selected.")
    print("[run] models:", models)
    before = credits(c)
    print(f"[run] credits before: {before}")

    cells = build_cells(a.reps, a.paraphrases, a.t3_variants)
    if a.only_tests:
        cells = [x for x in cells if x["test"] in a.only_tests]
    prev = latest_good(a.out)
    done = {cid for cid, rec in prev.items() if not rec.get("error") and not is_truncated(rec)}
    redo = [cid for cid, rec in prev.items() if cid not in done]
    if redo:
        print(f"[run] {len(redo)} earlier cells were empty or cut off at the token ceiling; they will be re-run")
    jobs = []
    for m in models:
        for cell in cells:
            cid = cell_id(m, cell["test"], cell["item"], cell.get("quality", ""), cell["frame"], cell.get("variant", ""), cell["para"], cell["rep"])
            if cid in done:
                continue
            jobs.append((m, dict(cell, cid=cid)))
    random.shuffle(jobs)
    print(f"[run] {len(cells)} cells x {len(models)} models = {len(cells)*len(models)} calls-ish; {len(jobs)} to do, {len(done)} already done")

    n_ok = n_err = 0
    spent = spent_so_far(a.out)
    print(f"[run] already spent in {a.out}: ${spent:.3f}" + (f"; budget ${a.budget:.2f}" if a.budget else ""))
    stopped = False
    with ThreadPoolExecutor(max_workers=a.workers) as ex:
        it = iter(jobs)
        pending = set()
        def submit_next():
            try:
                m, cell = next(it)
            except StopIteration:
                return False
            pending.add(ex.submit(run_cell, c, m, cell, a.temperature))
            return True
        for _ in range(a.workers * 2):
            submit_next()
        i = 0
        while pending:
            done_f = next(as_completed(pending))
            pending.discard(done_f)
            rec = done_f.result(); i += 1
            append_jsonl(a.out, rec)
            spent += rec_cost(rec)
            if rec.get("error"): n_err += 1
            else: n_ok += 1
            if i % 25 == 0 or i == len(jobs):
                print(f"[run] {i}/{len(jobs)} done  ok={n_ok} err={n_err}  spent=${spent:.3f}  credits={credits(c)}")
            if a.budget is not None and spent >= a.budget:
                if not stopped:
                    print(f"[run] BUDGET REACHED (${spent:.3f} >= ${a.budget:.2f}); finishing in-flight calls, submitting no more. Re-run later with a higher --budget to continue.")
                stopped = True
            elif not stopped:
                submit_next()
    after = credits(c)
    print(f"[run] finished. ok={n_ok} err={n_err}. spent this file=${spent:.3f}. credits before={before} after={after} delta={None if before is None or after is None else round(before-after, 3)}")
    if stopped:
        print("[run] NOTE: stopped by budget; remaining cells are untouched and will be picked up on the next run.")
    print(f"[run] output: {a.out}. Next: python judge.py --in {a.out}")


if __name__ == "__main__":
    main()
