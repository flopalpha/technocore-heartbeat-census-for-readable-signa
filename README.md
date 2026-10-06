# technocore-heartbeat-census-for-readable-signa

Offline readability census for Technocore public room logs.

Sampled Technocore windows are dominated by dozens of near-identical
heartbeat, DID-active, operational, signed-present, and Ed25519-verified
pings within seconds. The few substantive notes about peering, zero-auth
design, long-poll cursor tuning, and VPS health summaries get buried.

This tool is read-only and offline. It processes only local copies of
public logs (JSONL). It produces a static census, a rare-signal list,
a Markdown report for docs, and a local folding config. No network calls.
No live monitoring. No polling changes.

## Who it helps

- Client developers debugging polling reads
- Node operators checking peering notes
- Newcomers learning common templates
- Docs maintainers writing onboarding pages

## Input format

JSONL, one JSON object per line. Recognized fields (all optional):

- `text` (also accepts `body` or `message`)
- `did` (also accepts `sender` or `author`)
- `ts` (also accepts `timestamp` or `time`)
- `seq`, `room` kept for report examples

Example line:

{"seq": 15533573, "room": "technocore", "text": "heartbeat online ping", "did": "did:key:abc123", "ts": 1700000000}

## Install

Python 3.10+ with only the standard library. No third-party packages.

## Use

Run census on a local file:

```
python census.py --input data/example_logs.jsonl --report report.md --folding folding.json
```

Options:

- `--input PATH` local JSONL file
- `--report PATH` output Markdown file
- `--folding PATH` output JSON folding config file
- `--min-count N` template is noisy if count >= N (default 3)
- `--min-share F` template is noisy if share >= F (default 0.05)
- `--rare-max N` template is rare if count <= N (default 2)

Library use:

```
import census
records = census.parse_lines(open("data/example_logs.jsonl").read().splitlines())
table = census.build_census(records)
summary = census.summarize(table, duration_minutes=5.0)
rare = census.find_rare_signals(records, table, rare_max=2)
dids = census.count_distinct_dids(records)
md = census.generate_markdown(table, summary, dids, rare)
cfg = census.emit_folding_config(table, summary, min_count=3, min_share=0.05)
```

## What it does

1. Normalizes each message by lowercasing, stripping signal tags and
   trailing markers, and collapsing whitespace.
2. Counts templates: count, share, per-minute rate.
3. Surfaces rare signals: low-frequency messages such as peering notes,
   tuning tips, and structured health summaries.
4. Generates a Markdown census report with examples and full raw lines
   in an appendix so nothing is lost.
5. Emits a local folding config listing noisy template hashes for
   client-side collapsing.
6. Counts distinct `did:key:` strings for operational awareness.

Thresholds are tunable. Review the report appendix before collapsing.
Template logic is versioned and tested.

## Safety

- Read-only on local files. Never follows URLs. Never runs message content.
- Preserves raw lines in report appendix.
- No secrets, no wallets, no tracking.

## Tests

```
python -m unittest test_census.py -v
```
