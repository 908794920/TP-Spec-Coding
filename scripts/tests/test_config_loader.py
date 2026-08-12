# -*- coding: utf-8 -*-
"""Unit tests for the controlled YAML loader error codes (V5.1.0 C-01.4).

Pure stdlib unittest; offline; each governed error code (10-15) has at least
one positive rejection, plus success paths on the real V5.1.0 governance
files and the full-exact-match contract gate (ruling 8.6-M2). Every crafted
malformed sample lives in a temp dir; nothing touches the network, external
projects, or databases. Run:

    python scripts/tests/test_config_loader.py
"""

from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent.parent  # ai-work-base
sys.path.insert(0, str(BASE))
ACTIVE_VERSION = (BASE / "VERSION").read_text(encoding="utf-8").strip()

from cli import config_loader as cl  # noqa: E402


def write_tmp(text: str) -> str:
    fd = tempfile.NamedTemporaryFile("w", suffix=".yaml", delete=False, encoding="utf-8")
    fd.write(text)
    fd.close()
    return fd.name


class TestErrorCodes(unittest.TestCase):
    def _assert_code(self, code, text, **kw):
        path = write_tmp(text)
        try:
            with self.assertRaises(cl.ConfigLoadError) as ctx:
                cl.load_config(path, **kw)
            self.assertEqual(ctx.exception.error_code, code, ctx.exception.message)
            return ctx.exception
        finally:
            Path(path).unlink(missing_ok=True)

    def test_yaml_syntax(self):
        exc = self._assert_code(cl.ErrorCode.YAML_SYNTAX, "key: value\n\tbad: tabindent\n")
        self.assertEqual(exc.exit_code, 10)

    def test_duplicate_key(self):
        exc = self._assert_code(
            cl.ErrorCode.DUPLICATE_KEY,
            "states:\n  NEW: a\nother: 1\nstates:\n  NEW: b\n",
        )
        self.assertEqual(exc.exit_code, 11)

    def test_duplicate_key_nested(self):
        self._assert_code(
            cl.ErrorCode.DUPLICATE_KEY,
            "top:\n  k: 1\n  k: 2\n",
        )

    def test_unknown_field(self):
        text = (
            f'version: "{ACTIVE_VERSION}"\n'
            "workflow: {}\nstates: {}\nlevels: {}\ntransitions: {}\nrules: {}\n"
            "surprise_field: 1\n"
        )
        exc = self._assert_code(cl.ErrorCode.UNKNOWN_FIELD, text, schema_name="workflow")
        self.assertEqual(exc.exit_code, 12)

    def test_type_mismatch(self):
        # version parsed as float instead of str
        text = (
            "version: 5.05\n"
            "workflow: {}\nstates: {}\nlevels: {}\ntransitions: {}\nrules: {}\n"
        )
        exc = self._assert_code(cl.ErrorCode.TYPE_MISMATCH, text, schema_name="workflow")
        self.assertEqual(exc.exit_code, 13)

    def test_type_mismatch_missing_required(self):
        # valid version, but required 'states' field omitted
        text = (f'version: "{ACTIVE_VERSION}"\n' "workflow: {}\nlevels: {}\ntransitions: {}\nrules: {}\n")
        self._assert_code(cl.ErrorCode.TYPE_MISMATCH, text, schema_name="workflow")

    def test_version_mismatch(self):
        text = (
            'version: "9.9.9"\n'
            "workflow: {}\nstates: {}\nlevels: {}\ntransitions: {}\nrules: {}\n"
        )
        exc = self._assert_code(cl.ErrorCode.VERSION_MISMATCH, text, schema_name="workflow")
        self.assertEqual(exc.exit_code, 14)

    def test_resource_limit_nesting(self):
        # build deeper than MAX_NESTING_DEPTH nested mappings
        lines = []
        for i in range(cl.MAX_NESTING_DEPTH + 5):
            lines.append("  " * i + f"k{i}:")
        lines.append("  " * (cl.MAX_NESTING_DEPTH + 5) + "leaf: 1")
        exc = self._assert_code(cl.ErrorCode.RESOURCE_LIMIT, "\n".join(lines) + "\n")
        self.assertEqual(exc.exit_code, 15)


class TestSuccessPaths(unittest.TestCase):
    def test_all_governance_validate(self):
        from cli import config_schemas
        for name in ("workflow", "ai-role", "risk-rule", "knowledge-rule",
                     "orchestration", "role-catalog", "compat-matrix"):
            rel = config_schemas.get_schema(name)["file"]
            data = cl.load_config(rel, schema_name=name, base_root=str(BASE))
            self.assertIsInstance(data, dict)

    def test_status_template_validate(self):
        data = cl.load_config(
            f"templates/{ACTIVE_VERSION}/status.yaml", schema_name="status-template", base_root=str(BASE)
        )
        self.assertEqual(cl._get_dotted(data, "artifact_contract.version"), ACTIVE_VERSION)

    def test_knowledge_rule_uses_content_systems_path_authority(self):
        import json
        data = cl.load_config("governance/knowledge-rule.yaml",
                              schema_name="knowledge-rule", base_root=str(BASE))
        text = json.dumps(data, ensure_ascii=False)
        self.assertIn("Content Systems", text)
        self.assertNotIn("PRIVATE_VAULT_ROOT", text)
        self.assertIn("tp-knowledge", text)

    def test_get_state_owner(self):
        self.assertEqual(cl.get_state_owner("NEW", base_root=str(BASE)),
                         "tp-architecture-design")
        # Legacy owners remain decodable internally, but are not active workflow states.
        self.assertEqual(cl.get_state_owner("CLOSING", base_root=str(BASE)),
                         "tp-delivery-convergence")

    def test_workflow_transitions(self):
        tr = cl.get_workflow_transitions(base_root=str(BASE))
        self.assertIn("ACTIVE", tr["NEW"])
        self.assertIn("COMPLETED", tr["ACTIVE"])


class TestContractGate(unittest.TestCase):
    def test_gate_exact_match_accepts(self):
        # dynamically read current version from VERSION file
        current_version = cl.read_base_version(base_root=str(BASE))
        cl.gate_task_contract(current_version, base_root=str(BASE))  # no raise

    def test_gate_minor_diff_rejected(self):
        current_version = cl.read_base_version(base_root=str(BASE))
        major, minor, _ = current_version.split(".")
        other_minor = f"{major}.{int(minor) + 1}.0"
        with self.assertRaises(cl.ConfigLoadError) as ctx:
            cl.gate_task_contract(other_minor, base_root=str(BASE))
        self.assertEqual(ctx.exception.error_code, cl.ErrorCode.VERSION_MISMATCH)

    def test_gate_patch_diff_rejected(self):
        legacy_patch = ".".join(["5", "1", "1"])
        with self.assertRaises(cl.ConfigLoadError) as ctx:
            cl.gate_task_contract(legacy_patch, base_root=str(BASE))
        self.assertEqual(ctx.exception.error_code, cl.ErrorCode.VERSION_MISMATCH)


if __name__ == "__main__":
    unittest.main(verbosity=2)
