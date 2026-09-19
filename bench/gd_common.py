"""Shared helpers for the Gratification Drift benchmark."""
import json, os, re, time, hashlib, sys
from pathlib import Path

try:
    from openai import OpenAI
except ImportError:
    print("Missing dependency. Run:  pip install openai", file=sys.stderr)
    raise

BASE_URL = "https://openrouter.ai/api/v1"
HEADERS = {"HTTP-Referer": "https://ignostiq.com", "X-Title": "Gratification Drift benchmark"}

# Family regexes used to auto-pick the newest production model per family from /models.
FAMILIES = {
    "claude":   r"^anthropic/claude-(sonnet|opus)",
    "gpt":      r"^openai/gpt-5",
    "gemini":   r"^google/gemini-[0-9.]+-pro",
    "deepseek": r"^deepseek/deepseek-(chat|v3|v4)",
    "llama":    r"^meta-llama/llama-4",
    "qwen":     r"^qwen/qwen3?-(max|235b|plus)",
}
EXCLUDE = r"(free|preview|exp|beta|thinking|mini|nano|flash|lite|haiku|distill|instruct-turbo|:extended|:online|:nitro)"


def client():
    key = os.environ.get("OPENROUTER_API_KEY")
    if not key:
        sys.exit("Set OPENROUTER_API_KEY first (export OPENROUTER_API_KEY=sk-or-...)")
    return OpenAI(base_url=BASE_URL, api_key=key, default_headers=HEADERS, timeout=120, max_retries=3)


def list_models(c):
    import httpx
    r = httpx.get(BASE_URL + "/models", timeout=60)
    r.raise_for_status()
    return r.json()["data"]


def pick_models(c, families=None, verbose=True):
    """Newest model per family by 'created' timestamp, excluding previews/minis."""
    data = list_models(c)
    chosen = {}
    for fam, rx in FAMILIES.items():
        if families and fam not in families:
            continue
        cands = [m for m in data if re.search(rx, m["id"]) and not re.search(EXCLUDE, m["id"])]
        if not cands:
            if verbose: print(f"[models] no candidate for {fam}")
            continue
        cands.sort(key=lambda m: m.get("created", 0), reverse=True)
        chosen[fam] = cands[0]["id"]
        if verbose:
            print(f"[models] {fam:9s} -> {cands[0]['id']}   (alternatives: {', '.join(m['id'] for m in cands[1:4])})")
    return chosen


def credits(c):
    import httpx
    try:
        r = httpx.get(BASE_URL + "/credits", headers={"Authorization": "Bearer " + os.environ["OPENROUTER_API_KEY"]}, timeout=30)
        d = r.json()["data"]
        return d.get("total_credits", 0) - d.get("total_usage", 0)
    except Exception as e:
        return None


def chat(c, model, messages, temperature=None, max_tokens=3000, extra=None):
    body = {"usage": {"include": True}}
    if extra:
        body.update(extra)
    kw = dict(model=model, messages=messages, max_tokens=max_tokens, extra_body=body)
    if temperature is not None:
        kw["temperature"] = temperature
    for attempt in range(4):
        try:
            r = c.chat.completions.create(**kw)
            txt = r.choices[0].message.content or ""
            u = getattr(r, "usage", None)
            usage = {"prompt": getattr(u, "prompt_tokens", None), "completion": getattr(u, "completion_tokens", None), "cost_usd": getattr(u, "cost", None), "max_tokens": max_tokens, "finish_reason": getattr(r.choices[0], "finish_reason", None)} if u else {"max_tokens": max_tokens}
            try:
                det = getattr(u, "completion_tokens_details", None)
                if det is not None:
                    usage["reasoning_tokens"] = getattr(det, "reasoning_tokens", None)
            except Exception:
                pass
            if usage.get("cost_usd") is None and u is not None:
                try:
                    usage["cost_usd"] = u.model_extra.get("cost") if getattr(u, "model_extra", None) else None
                except Exception:
                    pass
            return txt, usage, None
        except Exception as e:
            err = str(e)
            time.sleep(2 * (attempt + 1))
    return "", {}, err


def cell_id(*parts):
    return hashlib.sha1("|".join(map(str, parts)).encode()).hexdigest()[:12]


def load_jsonl(path):
    p = Path(path)
    if not p.exists():
        return []
    return [json.loads(l) for l in p.read_text(encoding="utf-8").splitlines() if l.strip()]


def append_jsonl(path, rec):
    with open(path, "a", encoding="utf-8") as f:
        f.write(json.dumps(rec, ensure_ascii=False) + "\n")


def rec_cost(rec):
    """Total USD cost recorded in a response record (single or multi-turn)."""
    if "turns" in rec:
        return sum((t.get("usage") or {}).get("cost_usd") or 0 for t in rec["turns"])
    return (rec.get("usage") or {}).get("cost_usd") or 0


def spent_so_far(path):
    return sum(rec_cost(r) for r in load_jsonl(path))


def is_truncated(rec):
    """True if a single-turn record is empty or hit its token ceiling (or any turn of a multi-turn one did)."""
    def bad(text, usage):
        usage = usage or {}
        if not (text or "").strip():
            return True
        cap = usage.get("max_tokens") or 900
        if usage.get("finish_reason") == "length":
            return True
        comp = usage.get("completion")
        return comp is not None and comp >= cap
    if "turns" in rec:
        return any(bad(t.get("assistant"), t.get("usage")) for t in rec["turns"])
    return bad(rec.get("assistant"), rec.get("usage"))


def latest_good(path):
    """Records deduplicated by cid, keeping the last non-error, non-truncated one (or the last one if none is good)."""
    best = {}
    for r in load_jsonl(path):
        cid = r.get("cid")
        if cid is None:
            continue
        ok = not r.get("error") and not is_truncated(r)
        prev = best.get(cid)
        if prev is None or ok or (not prev[1]):
            if prev is None or ok or not prev[1]:
                best[cid] = (r, ok)
    return {cid: r for cid, (r, ok) in best.items()}
