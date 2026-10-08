"""Check packet blinding and prevent incompatible human-label imports."""

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import p4_gate_closeout as g


class CloseoutTests(unittest.TestCase):
    def test_packet_matches_visible_sources_without_outcome_metadata(self):
        packet = g.c.p4.read(g.OUT / "annotation_packet.json")
        manifest = g.c.p4.read(g.OUT / "annotation_manifest.json")
        self.assertEqual(len(packet), 48)
        self.assertEqual(g.c.p4.digest(packet), manifest["packet_sha256"])
        for entry, mapping in zip(packet, manifest["mapping"], strict=True):
            self.assertEqual(
                set(entry), {"episode_id", "policy", "agent_tools", "transcript"}
            )
            source = g.c.p4.read(
                g.OUT.parent
                / mapping["batch"]
                / "sources"
                / (mapping["sample_id"] + ".json")
            )
            self.assertEqual(entry["transcript"], g.c.p4.agent_view(source["messages"]))

    def test_wrong_packet_human_export_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "input.json"
            path.write_text(
                json.dumps(
                    {
                        "annotation_type": "human_candidate_review",
                        "reviewer_id": "fixture",
                        "packet_sha256": "wrong",
                        "entries": [],
                    }
                )
            )
            with self.assertRaisesRegex(ValueError, "packet hash"):
                g.import_annotations(path)

    def test_partial_human_input_is_saved_without_promoting_causal_failures(self):
        packet = g.c.p4.read(g.OUT / "annotation_packet.json")
        manifest = g.c.p4.read(g.OUT / "annotation_manifest.json")
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "annotation_packet.json").write_text(json.dumps(packet))
            (root / "annotation_manifest.json").write_text(json.dumps(manifest))
            path = root / "input.json"
            path.write_text(
                json.dumps(
                    {
                        "annotation_type": "human_candidate_review",
                        "reviewer_id": "fixture",
                        "packet_sha256": manifest["packet_sha256"],
                        "entries": [
                            {
                                "episode_id": packet[0]["episode_id"],
                                "category": "uncertain",
                                "prior_exposure": "yes",
                            }
                        ],
                    }
                )
            )
            with patch.object(g, "OUT", root):
                g.import_annotations(path)
            self.assertEqual(len(list((root / "human_annotations").glob("*.json"))), 1)
            self.assertFalse((root / "evidence_registry.json").exists())


if __name__ == "__main__":
    unittest.main()
