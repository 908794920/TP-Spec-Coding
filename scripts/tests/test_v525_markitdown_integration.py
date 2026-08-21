# -*- coding: utf-8 -*-
"""V5.2.6 MarkItDown document-normalization integration regression."""
from __future__ import annotations

import importlib
import json
from pathlib import Path

import pytest
import yaml

from cli.content_systems import load_content_systems

BASE = Path(__file__).resolve().parents[2]


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8", newline="\n")


def _knowledge_cfg(tmp_path: Path):
    workspace = tmp_path / "workspace"
    vault = tmp_path / "vault"
    workspace.mkdir()
    vault.mkdir()
    _write(
        workspace / ".tp-spec/config/content-systems.yaml",
        f'''schema: tp-spec.content-systems/v1
systems:
  knowledge:
    root: "{vault.as_posix()}"
''',
    )
    _write(
        vault / "00-system/project-registry.yaml",
        f'''registry_version: "1.0.0"
projects:
  - id: demo
    display_name: Demo
    source_dir: Demo
    aliases: [Demo]
    status: active
    workspace_roots:
      - "{workspace.as_posix()}"
shared_scopes: []
''',
    )
    return workspace, vault, load_content_systems(workspace)


def _frontmatter(path: Path) -> dict:
    text = path.read_text(encoding="utf-8")
    assert text.startswith("---\n")
    return yaml.safe_load(text.split("---", 2)[1])


def test_user_facing_entry_skill_name_changes_without_renaming_internal_ids():
    entry = _frontmatter(BASE / "entry/tp-spec-coding/SKILL.md")
    lifecycle = _frontmatter(BASE / "agents/tp-software-lifecycle/SKILL.md")

    assert entry["id"] == "tp-spec-coding"
    assert entry["role"] == "tp-spec-coding"
    assert entry["name"] == "tp-软件生命周期"
    # Internal Domain Agent identity/display is not part of this user-facing rename.
    assert lifecycle["id"] == "tp-software-lifecycle"
    assert lifecycle["name"] == "tp-软件工程生命周期"


def test_local_document_conversion_uses_markitdown_convert_local_and_writes_markdown(tmp_path, monkeypatch):
    module = importlib.import_module("cli.document_conversion")
    source = tmp_path / "需求.docx"
    output = tmp_path / "normalized" / "需求.docx.md"
    source.write_bytes(b"fake-docx")
    calls = []

    class Result:
        markdown = "# Converted\n\nrequirement body\n"

    class FakeMarkItDown:
        def __init__(self, **kwargs):
            calls.append(("init", kwargs))

        def convert(self, *_args, **_kwargs):
            raise AssertionError("broad convert() must not be used for local-only TP conversion")

        def convert_local(self, path):
            calls.append(("convert_local", Path(path)))
            return Result()

    monkeypatch.setattr(module, "_load_markitdown", lambda: (FakeMarkItDown, "0.1.7"))

    result = module.convert_local_file(source, output)

    assert output.read_text(encoding="utf-8") == Result.markdown
    assert calls[0] == ("init", {"enable_plugins": False})
    assert calls[1] == ("convert_local", source.resolve())
    assert result["converter"] == {"name": "microsoft/markitdown", "version": "0.1.7", "api": "convert_local"}
    assert result["source_sha256"]
    assert result["output_sha256"]


def test_local_document_conversion_refuses_implicit_overwrite(tmp_path):
    module = importlib.import_module("cli.document_conversion")
    source = tmp_path / "source.txt"
    output = tmp_path / "out.md"
    source.write_text("source", encoding="utf-8")
    output.write_text("keep", encoding="utf-8")

    with pytest.raises(FileExistsError, match="output already exists"):
        module.convert_local_file(source, output)

    assert output.read_text(encoding="utf-8") == "keep"


def test_cli_exposes_explicit_local_document_convert_command():
    from cli.main import build_parser

    args = build_parser().parse_args(
        ["document", "convert", "--source", "input.docx", "--output", "input.docx.md"]
    )
    assert args.group == "document"
    assert args.document_cmd == "convert"
    assert args.source == "input.docx"
    assert args.output == "input.docx.md"


def test_knowledge_batch_converts_registered_source_without_advancing_disposition(tmp_path, monkeypatch):
    from cli.knowledge import ingest

    _workspace, vault, cfg = _knowledge_cfg(tmp_path)
    source_root = tmp_path / "external"
    source_root.mkdir()
    source = source_root / "需求说明.docx"
    source.write_bytes(b"registered-docx")
    ingest.register_batch(cfg, project="demo", batch="B1", source_root=source_root)

    def fake_convert(src: Path, out: Path, *, overwrite: bool = False):
        assert Path(src) == source.resolve()
        assert overwrite is True
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text("# Requirement\n", encoding="utf-8", newline="\n")
        return {
            "converter": {"name": "microsoft/markitdown", "version": "0.1.7", "api": "convert_local"},
            "source_sha256": ingest._sha256(Path(src)),
            "output_sha256": ingest._sha256(Path(out)),
        }

    monkeypatch.setattr(ingest, "markitdown_runtime", lambda: {"name": "microsoft/markitdown", "version": "0.1.7", "api": "convert_local"}, raising=False)
    monkeypatch.setattr(ingest, "convert_local_file", fake_convert, raising=False)

    result = ingest.convert_batch(cfg, batch="B1")

    assert result["status"] == "PASS"
    assert result["converted"] == 1
    assert result["quarantined"] == 0
    assert result["skipped"] == 0
    manifest = [json.loads(x) for x in (vault / ".ai-kb/ingest/B1/manifest.jsonl").read_text(encoding="utf-8").splitlines()]
    assert len(manifest) == 1
    row = manifest[0]
    assert row["classification"] == "convert_candidate"
    assert row["disposition"] == "pending"
    assert row["conversion_status"] == "converted"
    assert row["conversion_path"] == ".ai-kb/ingest/B1/converted/需求说明.docx.md"
    assert (vault / row["conversion_path"]).read_text(encoding="utf-8") == "# Requirement\n"
    assert row["converter"] == "microsoft/markitdown"
    assert row["converter_version"] == "0.1.7"
    assert ingest.ingest_status(cfg, "B1")["pending"] == 1
    with pytest.raises(ValueError, match="accountability incomplete"):
        ingest.finalize_batch(cfg, "B1")


def test_spreadsheets_and_presentations_are_now_convert_candidates(tmp_path):
    from cli.knowledge import ingest

    _workspace, vault, cfg = _knowledge_cfg(tmp_path)
    source_root = tmp_path / "external"
    source_root.mkdir()
    (source_root / "table.xlsx").write_bytes(b"xlsx")
    (source_root / "deck.pptx").write_bytes(b"pptx")
    ingest.register_batch(cfg, project="demo", batch="B2", source_root=source_root)

    rows = [json.loads(x) for x in (vault / ".ai-kb/ingest/B2/manifest.jsonl").read_text(encoding="utf-8").splitlines()]
    assert {row["classification"] for row in rows} == {"convert_candidate"}


def test_conversion_failure_quarantines_only_the_failed_source(tmp_path, monkeypatch):
    from cli.knowledge import ingest

    _workspace, vault, cfg = _knowledge_cfg(tmp_path)
    source_root = tmp_path / "external"
    source_root.mkdir()
    (source_root / "broken.pdf").write_bytes(b"broken-pdf")
    ingest.register_batch(cfg, project="demo", batch="B3", source_root=source_root)

    monkeypatch.setattr(ingest, "markitdown_runtime", lambda: {"name": "microsoft/markitdown", "version": "0.1.7", "api": "convert_local"}, raising=False)
    monkeypatch.setattr(ingest, "convert_local_file", lambda *_a, **_k: (_ for _ in ()).throw(ValueError("cannot parse")), raising=False)

    result = ingest.convert_batch(cfg, batch="B3")

    assert result["status"] == "PASS"
    assert result["converted"] == 0
    assert result["quarantined"] == 1
    row = json.loads((vault / ".ai-kb/ingest/B3/manifest.jsonl").read_text(encoding="utf-8").strip())
    assert row["disposition"] == "quarantined"
    assert row["conversion_status"] == "failed"
    assert row["reason"].startswith("conversion-failed:ValueError:")


def test_source_change_after_registration_blocks_conversion_without_mutating_manifest(tmp_path, monkeypatch):
    from cli.knowledge import ingest

    _workspace, vault, cfg = _knowledge_cfg(tmp_path)
    source_root = tmp_path / "external"
    source_root.mkdir()
    source = source_root / "changed.docx"
    source.write_bytes(b"v1")
    ingest.register_batch(cfg, project="demo", batch="B4", source_root=source_root)
    before = (vault / ".ai-kb/ingest/B4/manifest.jsonl").read_text(encoding="utf-8")
    source.write_bytes(b"v2")

    monkeypatch.setattr(ingest, "markitdown_runtime", lambda: {"name": "microsoft/markitdown", "version": "0.1.7", "api": "convert_local"}, raising=False)
    called = []
    monkeypatch.setattr(ingest, "convert_local_file", lambda *_a, **_k: called.append(True), raising=False)

    with pytest.raises(ValueError, match="changed since registration"):
        ingest.convert_batch(cfg, batch="B4")

    assert called == []
    assert (vault / ".ai-kb/ingest/B4/manifest.jsonl").read_text(encoding="utf-8") == before


def test_markitdown_runtime_dependency_and_operator_docs_are_pinned():
    requirements = (BASE / "requirements.txt").read_text(encoding="utf-8")
    notices = (BASE / "THIRD_PARTY_NOTICES.md").read_text(encoding="utf-8")
    knowledge_skill = (BASE / "agents/tp-knowledge/SKILL.md").read_text(encoding="utf-8")
    product_skill = (BASE / "skills/roles/tp-product-manager/SKILL.md").read_text(encoding="utf-8")

    assert "markitdown[pdf,docx,xlsx,xls,pptx]==0.1.7" in requirements
    assert "Microsoft MarkItDown" in notices
    assert "MIT" in notices
    assert "tp-spec knowledge ingest convert" in knowledge_skill
    assert "tp-spec document convert" in product_skill
