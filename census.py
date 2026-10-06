"""Offline heartbeat census for readable signal."""
import argparse
import hashlib
import json
import re
import sys

TEMPLATE_VERSION = "v1"

TAG_RE = re.compile(r"\[(heartbeat|ping|presence|operational|beacon)\]", re.IGNORECASE)
HASH_RE = re.compile(r"#[A-Za-z0-9_\-]+")
SPACE_RE = re.compile(r"\s+")
TRAIL_RE = re.compile(r"[\s\.\!\*\-\~\>\/\\\|_:;,#]+$")


def normalize_message(text):
    """Lowercase, remove tags, strip trailing markers, collapse spaces."""
    if not isinstance(text, str):
        return ""
    s = text.lower()
    s = TAG_RE.sub(" ", s)
    s = HASH_RE.sub(" ", s)
    s = s.strip()
    s = TRAIL_RE.sub("", s)
    s = SPACE_RE.sub(" ", s)
    s = s.strip()
    s = TRAIL_RE.sub("", s)
    return s


def template_hash(normalized):
    h = hashlib.sha256(normalized.encode("utf-8")).hexdigest()
    return h[:16]


def get_text(obj):
    for key in ("text", "body", "message"):
        val = obj.get(key)
        if isinstance(val, str) and val.strip():
            return val
    return ""


def get_did(obj):
    for key in ("did", "sender", "author"):
        val = obj.get(key)
        if isinstance(val, str) and val.strip():
            return val.strip()
    return ""


def get_ts(obj):
    for key in ("ts", "timestamp", "time"):
        val = obj.get(key)
        if isinstance(val, (int, float)):
            return float(val)
    return None


def parse_lines(lines):
    records = []
    for line in lines:
        if not isinstance(line, str):
            continue
        if not line.strip():
            continue
        try:
            obj = json.loads(line)
        except ValueError:
            continue
        if not isinstance(obj, dict):
            continue
        raw = get_text(obj)
        norm = normalize_message(raw)
        if not norm:
            continue
        rec = {
            "raw": raw,
            "norm": norm,
            "tid": template_hash(norm),
            "did": get_did(obj),
            "ts": get_ts(obj),
            "seq": obj.get("seq"),
            "room": obj.get("room", ""),
        }
        records.append(rec)
    return records


def load_jsonl(path):
    with open(path, "r", encoding="utf-8") as f:
        lines = f.read().splitlines()
    return parse_lines(lines)


def build_census(records):
    table = {}
    for rec in records:
        norm = rec["norm"]
        entry = table.get(norm)
        if entry is None:
            table[norm] = {
                "count": 1,
                "tid": rec["tid"],
                "example": rec["raw"],
                "seqs": [rec.get("seq")],
            }
        else:
            entry["count"] += 1
            if len(entry["seqs"]) < 5:
                entry["seqs"].append(rec.get("seq"))
    return table


def estimate_duration_minutes(records):
    stamps = [r["ts"] for r in records if isinstance(r.get("ts"), float)]
    if len(stamps) < 2:
        return 1.0
    span = max(stamps) - min(stamps)
    if span < 1.0:
        return 1.0 / 60.0
    return span / 60.0


def summarize(table, duration_minutes):
    total = 0
    for entry in table.values():
        total += entry["count"]
    if duration_minutes <= 0:
        duration_minutes = 1.0
    rows = []
    for norm, entry in table.items():
        count = entry["count"]
        share = count / total if total else 0.0
        rate = count / duration_minutes
        rows.append({
            "template": norm,
            "tid": entry["tid"],
            "count": count,
            "share": share,
            "per_min": rate,
            "example": entry["example"],
        })
    rows.sort(key=lambda r: r["count"], reverse=True)
    return rows


def pick_noisy(rows, min_count=3, min_share=0.05):
    noisy = []
    for row in rows:
        if row["count"] >= min_count and row["share"] >= min_share:
            noisy.append(row)
    return noisy


def find_rare_signals(records, table, rare_max=2):
    rare = []
    for rec in records:
        entry = table.get(rec["norm"])
        if entry is None:
            continue
        if entry["count"] <= rare_max:
            rare.append(rec)
    return rare


def count_distinct_dids(records):
    seen = set()
    for rec in records:
        did = rec.get("did", "")
        if isinstance(did, str) and did.startswith("did:key:"):
            seen.add(did)
    return len(seen)


def emit_folding_config(rows, min_count=3, min_share=0.05):
    noisy = pick_noisy(rows, min_count=min_count, min_share=min_share)
    hashes = sorted([r["tid"] for r in noisy])
    return {
        "version": 1,
        "template_version": TEMPLATE_VERSION,
        "min_count": min_count,
        "min_share": min_share,
        "noisy_template_hashes": hashes,
    }


def generate_markdown(table, rows, distinct_dids, rare, duration_minutes, total):
    out = []
    out.append("# Technocore Heartbeat Census")
    out.append("")
    out.append("Template version: " + TEMPLATE_VERSION)
    out.append("Total messages: " + str(total))
    out.append("Distinct templates: " + str(len(table)))
    out.append("Distinct did:key count: " + str(distinct_dids))
    out.append("Window minutes: " + str(round(duration_minutes, 3)))
    out.append("")
    out.append("## Template census")
    out.append("")
    out.append("| count | share | per-min | template | hash |")
    out.append("| --- | --- | --- | --- | --- |")
    for row in rows:
        share_txt = str(round(row["share"] * 100.0, 2)) + "%"
        rate_txt = str(round(row["per_min"], 3))
        tpl = row["template"]
        if len(tpl) > 80:
            tpl = tpl[:77] + "..."
        tpl = tpl.replace("|", " ")
        line = "| " + str(row["count"]) + " | " + share_txt
        line = line + " | " + rate_txt + " | " + tpl
        line = line + " | " + row["tid"] + " |"
        out.append(line)
    out.append("")
    out.append("## Rare signals")
    out.append("")
    if not rare:
        out.append("No rare signals found.")
    else:
        for rec in rare[:50]:
            seq = rec.get("seq")
            raw = rec.get("raw", "")
            if len(raw) > 200:
                raw = raw[:197] + "..."
            raw = raw.replace("\n", " ")
            out.append("- seq=" + str(seq) + " : " + raw)
    out.append("")
    out.append("## Template examples")
    out.append("")
    for row in rows[:20]:
        out.append("- hash=" + row["tid"] + " count=" + str(row["count"]))
        out.append("  example: " + row["example"][:200].replace("\n", " "))
    out.append("")
    out.append("## Appendix: raw lines")
    out.append("")
    return "\n".join(out)


def run(input_path, report_path, folding_path, min_count=3, min_share=0.05, rare_max=2):
    records = load_jsonl(input_path)
    table = build_census(records)
    duration = estimate_duration_minutes(records)
    rows = summarize(table, duration)
    rare = find_rare_signals(records, table, rare_max=rare_max)
    dids = count_distinct_dids(records)
    total = len(records)
    md = generate_markdown(table, rows, dids, rare, duration, total)
    cfg = emit_folding_config(rows, min_count=min_count, min_share=min_share)
    with open(report_path, "w", encoding="utf-8") as f:
        f.write(md)
        f.write("\n")
        for rec in records:
            f.write("- " + rec["raw"].replace("\n", " ")[:300] + "\n")
    with open(folding_path, "w", encoding="utf-8") as f:
        json.dump(cfg, f, indent=2, sort_keys=True)
        f.write("\n")
    return {"total": total, "templates": len(table), "dids": dids}


def main(argv=None):
    parser = argparse.ArgumentParser(description="Offline heartbeat census")
    parser.add_argument("--input", required=True, help="local JSONL file")
    parser.add_argument("--report", required=True, help="output markdown")
    parser.add_argument("--folding", required=True, help="output json")
    parser.add_argument("--min-count", type=int, default=3)
    parser.add_argument("--min-share", type=float, default=0.05)
    parser.add_argument("--rare-max", type=int, default=2)
    args = parser.parse_args(argv)
    result = run(args.input, args.report, args.folding, args.min_count, args.min_share, args.rare_max)
    sys.stdout.write(json.dumps(result, sort_keys=True) + "\n")
    return 0


if __name__ == "__main__":
    main()
