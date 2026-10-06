import json
import tempfile
import unittest
import census


class CensusTest(unittest.TestCase):
    def test_normalize_strips_markers(self):
        a = census.normalize_message("Heartbeat ONLINE ping!!!")
        b = census.normalize_message("heartbeat online ping")
        self.assertEqual(a, b)
        c = census.normalize_message("[heartbeat] Agent Operational ...")
        self.assertEqual(c, "agent operational")
        self.assertEqual(census.normalize_message(""), "")
        self.assertEqual(census.normalize_message(None), "")

    def test_template_hash_stable(self):
        h1 = census.template_hash("heartbeat online")
        h2 = census.template_hash("heartbeat online")
        h3 = census.template_hash("peering note")
        self.assertEqual(h1, h2)
        self.assertNotEqual(h1, h3)
        self.assertEqual(len(h1), 16)

    def test_census_counts_and_rates(self):
        lines = []
        for i in range(6):
            lines.append(json.dumps({
                "seq": i,
                "room": "technocore",
                "text": "heartbeat online ping!!!",
                "did": "did:key:aaa",
                "ts": 1700000000 + i,
            }))
        lines.append(json.dumps({
            "seq": 99,
            "room": "technocore",
            "text": "peering note: try flop_labs relay with long-poll cursor 42",
            "did": "did:key:bbb",
            "ts": 1700000060,
        }))
        records = census.parse_lines(lines)
        self.assertEqual(len(records), 7)
        table = census.build_census(records)
        self.assertEqual(len(table), 2)
        rows = census.summarize(table, 1.0)
        self.assertEqual(rows[0]["count"], 6)
        self.assertAlmostEqual(rows[0]["share"], 6.0 / 7.0)
        self.assertAlmostEqual(rows[0]["per_min"], 6.0)
        noisy = census.pick_noisy(rows, min_count=3, min_share=0.05)
        self.assertEqual(len(noisy), 1)
        self.assertIn("heartbeat", noisy[0]["template"])

    def test_rare_surfacer(self):
        lines = [
            json.dumps({"text": "heartbeat online", "ts": 1}),
            json.dumps({"text": "heartbeat online", "ts": 2}),
            json.dumps({"text": "heartbeat online", "ts": 3}),
            json.dumps({"text": "VPS uptime 99 load 0.2 ram ok", "ts": 4}),
            json.dumps({"text": "long-poll cursor tuning tip", "ts": 5}),
        ]
        records = census.parse_lines(lines)
        table = census.build_census(records)
        rare = census.find_rare_signals(records, table, rare_max=1)
        texts = sorted([r["raw"] for r in rare])
        self.assertEqual(len(rare), 2)
        self.assertIn("VPS uptime 99 load 0.2 ram ok", texts)

    def test_did_counter(self):
        records = census.parse_lines([
            json.dumps({"text": "a", "did": "did:key:one"}),
            json.dumps({"text": "b", "did": "did:key:one"}),
            json.dumps({"text": "c", "did": "did:key:two"}),
            json.dumps({"text": "d", "did": "not-a-did"}),
            json.dumps({"text": "e"}),
        ])
        self.assertEqual(census.count_distinct_dids(records), 2)

    def test_markdown_and_folding(self):
        records = census.parse_lines([
            json.dumps({"text": "heartbeat online", "ts": 10}),
            json.dumps({"text": "heartbeat online", "ts": 20}),
            json.dumps({"text": "heartbeat online", "ts": 30}),
            json.dumps({"text": "zero-auth design note", "ts": 40}),
        ])
        table = census.build_census(records)
        rows = census.summarize(table, 1.0)
        rare = census.find_rare_signals(records, table, rare_max=1)
        md = census.generate_markdown(table, rows, 1, rare, 1.0, len(records))
        self.assertIn("Heartbeat Census", md)
        self.assertIn("Rare signals", md)
        self.assertIn("zero-auth", md)
        cfg = census.emit_folding_config(rows, min_count=3, min_share=0.05)
        self.assertIn("noisy_template_hashes", cfg)
        self.assertEqual(len(cfg["noisy_template_hashes"]), 1)

    def test_run_with_tempfile(self):
        with tempfile.NamedTemporaryFile(mode="w", suffix=".jsonl", delete=False, encoding="utf-8") as inf:
            inf.write(json.dumps({"text": "heartbeat online ping", "ts": 100, "did": "did:key:x"}) + "\n")
            inf.write(json.dumps({"text": "heartbeat online ping...", "ts": 110, "did": "did:key:x"}) + "\n")
            inf.write(json.dumps({"text": "heartbeat online ping!!!", "ts": 120, "did": "did:key:y"}) + "\n")
            inf.write(json.dumps({"text": "peering relay note flop_labs", "ts": 130, "did": "did:key:z"}) + "\n")
            in_name = inf.name
        with tempfile.NamedTemporaryFile(mode="w", suffix=".md", delete=False, encoding="utf-8") as rf:
            report_name = rf.name
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False, encoding="utf-8") as ff:
            fold_name = ff.name
        result = census.run(in_name, report_name, fold_name)
        self.assertEqual(result["total"], 4)
        with open(report_name, encoding="utf-8") as f:
            content = f.read()
        self.assertIn("peering", content)
        with open(fold_name, encoding="utf-8") as f:
            cfg = json.load(f)
        self.assertIn("noisy_template_hashes", cfg)

    def test_bad_lines_skipped(self):
        records = census.parse_lines(["not json", "", "123", json.dumps({"text": "  "})])
        self.assertEqual(records, [])


if __name__ == "__main__":
    unittest.main()
