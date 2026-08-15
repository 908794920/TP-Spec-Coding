from __future__ import annotations

import hashlib
import json
import tempfile
from pathlib import Path

import yaml

from cli import namespace_migration
from cli.wiki import anchors
from cli.wiki.snapshot import build_current_snapshot


def write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8", newline="\n")


def _wiki_fixture(root: Path):
    workspace = root / "workspace"
    repo = root / "repo"
    wiki = root / "wiki-repo"
    workspace.mkdir(); repo.mkdir(); wiki.mkdir()
    write(repo / "src/A.java", "class A { int a = 1; }\n")
    write(repo / "src/B.java", "class B { int b = 2; }\n")
    write(wiki / "core.md", '# Core\n<cite path="src/A.java" line="1"/>\n<cite path="src/B.java" line="1"/>\n')
    manifest = {
        "schema": "tp-spec.wiki-manifest/v1",
        "workspace_id": "ws",
        "repo_id": "repo",
        "repo_root": str(repo),
        "documents": [{
            "path": "core.md", "type": "content-doc", "title": "Core", "status": "completed",
            "content_hash": hashlib.sha256((wiki / "core.md").read_bytes()).hexdigest(),
            "citations": [
                {"file": "src/A.java", "line_start": 1, "line_end": 1},
                {"file": "src/B.java", "line_start": 1, "line_end": 1},
            ],
            "dependencies": [],
        }],
    }
    write(wiki / "meta/wiki-manifest.yaml", yaml.safe_dump(manifest, allow_unicode=True, sort_keys=False))
    source_cfg = {"include_extensions": [".java"], "properties_normalization": "keys"}
    baseline = build_current_snapshot("repo", repo, source_cfg)
    write(wiki / "meta/wiki-snapshot.json", json.dumps(baseline, ensure_ascii=False, indent=2) + "\n")
    full = anchors.build_anchor_state(wiki_repo_root=wiki, repo_root=repo, source_cfg=source_cfg, snapshot_id=baseline["snapshot_id"])
    partial = dict(full)
    partial["sources"] = {"src/A.java": full["sources"]["src/A.java"]}
    partial["citations"] = [row for row in full["citations"] if row["source"] == "src/A.java"]
    write(wiki / "meta/wiki-cite-anchors.json", json.dumps(partial, ensure_ascii=False, indent=2) + "\n")
    return workspace, repo, wiki, source_cfg, baseline


def test_namespace_migrate_rewrites_resolved_legacy_central_wiki_meta_only_tokens():
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        workspace = root / "workspace"; workspace.mkdir()
        (workspace / ".tp-spec").mkdir()
        home = root / "home"; (home / ".tp-spec").mkdir(parents=True)
        vault = root / "central-wiki"
        write(vault / "00-system/repo-registry.yaml", "workspaces: []\n")
        meta = vault / "projects/idcproject/idc-collect/idc-collect-data-middle-quartz/meta"
        hash_value = "a" * 64
        legacy_schema_prefix = "ai" + "-work."
        write(meta / "wiki-manifest.yaml", f"schema: {legacy_schema_prefix}wiki-manifest/v1\ncontent_hash: {hash_value}\n")
        write(meta / "wiki-cite-anchors.json", json.dumps({
            "schema": legacy_schema_prefix + "wiki-cite-anchors/v1",
            "snapshot_id": "snap-keep",
            "sources": {"A.java": {"content_hash": hash_value, "semantic_lines": [{"line": 77, "sig": "abcd"}]}}
        }, ensure_ascii=False, indent=2) + "\n")
        write(home / ".tp-spec/installation.yaml", f'''schema: tp-spec.installation/v1
base:
  root: "{Path.cwd().as_posix()}"
systems:
  wiki:
    root: "{vault.as_posix()}"
  knowledge:
    root: "{(root / 'knowledge').as_posix()}"
''')

        plan = namespace_migration.namespace_plan(workspace, home=home)
        assert plan["wiki_machine_metadata"]["status"] == "MIGRATION_AVAILABLE"
        assert plan["wiki_machine_metadata"]["legacy_file_count"] == 2

        result = namespace_migration.migrate_namespace(workspace, home=home, apply=True)
        assert result["status"] == "PASS"
        manifest_text = (meta / "wiki-manifest.yaml").read_text(encoding="utf-8")
        anchor = json.loads((meta / "wiki-cite-anchors.json").read_text(encoding="utf-8"))
        assert "schema: tp-spec.wiki-manifest/v1" in manifest_text
        assert hash_value in manifest_text
        assert anchor["schema"] == "tp-spec.wiki-cite-anchors/v1"
        assert anchor["snapshot_id"] == "snap-keep"
        assert anchor["sources"]["A.java"]["content_hash"] == hash_value
        assert anchor["sources"]["A.java"]["semantic_lines"][0]["line"] == 77


def test_anchor_health_reports_partial_precise_source_coverage():
    with tempfile.TemporaryDirectory() as td:
        _, repo, wiki, source_cfg, baseline = _wiki_fixture(Path(td))
        report = anchors.anchor_health_report(wiki_repo_root=wiki, repo_root=repo, repo_id="repo", source_cfg=source_cfg)
        assert report["precise_cited_source_count"] == 2
        assert report["anchor_source_count"] == 1
        assert report["missing_source_count"] == 1
        assert report["missing_sources"] == ["src/B.java"]
        assert report["baseline_snapshot_id"] == baseline["snapshot_id"]
        assert report["source_baseline_current"] is True
        assert report["repairable"] is True


def test_anchor_repair_rebuilds_complete_baseline_when_source_and_wiki_subject_are_unchanged():
    with tempfile.TemporaryDirectory() as td:
        _, repo, wiki, source_cfg, _ = _wiki_fixture(Path(td))
        result = anchors.repair_anchor_baseline(
            wiki_repo_root=wiki, repo_root=repo, repo_id="repo", source_cfg=source_cfg, apply=True
        )
        assert result["status"] == "REPAIRED"
        repaired = json.loads((wiki / "meta/wiki-cite-anchors.json").read_text(encoding="utf-8"))
        assert sorted(repaired["sources"]) == ["src/A.java", "src/B.java"]
        assert len(repaired["citations"]) == 2


def test_anchor_repair_fails_closed_when_source_has_drifted_from_committed_snapshot():
    with tempfile.TemporaryDirectory() as td:
        _, repo, wiki, source_cfg, _ = _wiki_fixture(Path(td))
        write(repo / "src/B.java", "// cosmetic\nclass B { int b = 2; }\n")
        report = anchors.anchor_health_report(wiki_repo_root=wiki, repo_root=repo, repo_id="repo", source_cfg=source_cfg)
        assert report["source_baseline_current"] is False
        assert report["repairable"] is False
        try:
            anchors.repair_anchor_baseline(
                wiki_repo_root=wiki, repo_root=repo, repo_id="repo", source_cfg=source_cfg, apply=True
            )
        except ValueError as exc:
            assert "source baseline has drifted" in str(exc)
        else:
            raise AssertionError("repair must fail closed after source drift")


def test_new_recovery_cli_surfaces_are_registered():
    from cli import main as climain
    from cli.wiki import commands as wiki_commands
    from cli import base_maintenance

    parser = climain.build_parser()
    args = parser.parse_args(["wiki", "anchors-doctor", "--workspace-root", ".", "--repo", "demo"])
    assert args.func is wiki_commands.cmd_anchors_doctor
    args = parser.parse_args(["wiki", "anchors-repair", "--workspace-root", ".", "--repo", "demo", "--apply"])
    assert args.func is wiki_commands.cmd_anchors_repair and args.apply is True
    args = parser.parse_args(["base", "namespace-migrate", "--workspace-root", ".", "--installation-config", "x.yaml", "--apply"])
    assert args.func is base_maintenance.cmd_namespace_migrate
    assert args.installation_config == "x.yaml"
