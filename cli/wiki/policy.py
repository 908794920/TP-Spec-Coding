"""Exact policy-impact reviews; historical material is read only at explicit review."""
from pathlib import Path, PurePosixPath
import hashlib
import stat
import subprocess
import yaml

from .snapshot import _digest, _read_json, _write_json, _VOLATILE_META_NAMES, snapshot_paths, utc_now, wiki_subject_digest
from .source import sha256_bytes


def selected_rule(name, scope="maintenance"):
    path = PurePosixPath(name)
    selected = ((path.parent == PurePosixPath("cli/wiki") and path.suffix == ".py") or
                name == "cli/sensitive_scanner.py" or
                (path.suffix == ".md" and any(name.startswith(p + "/") for p in
                 ("wiki/rules", "agents/tp-wiki", "skills/wiki", "automation/wiki"))) or
                (path.parent == PurePosixPath("wiki/schema") and path.suffix == ".yaml"))
    return selected and (scope == "whole-all" or not (
        name in {"cli/wiki/retrieval.py", "cli/wiki/retrieval_commands.py"} or
        name.startswith("skills/wiki/tp-wiki-retrieval/")))


def current_rules(base, scope="maintenance"):
    return {p.relative_to(base).as_posix(): sha256_bytes(p.read_bytes())
            for folder in ("cli/wiki", "cli/sensitive_scanner.py", "wiki/rules", "agents/tp-wiki", "skills/wiki", "automation/wiki", "wiki/schema")
            for root in [base / folder] for p in ([root] if root.is_file() else root.rglob("*"))
            if p.is_file() and selected_rule(p.relative_to(base).as_posix(), scope)}


def archive_rules(base, output_root, *, scope="maintenance"):
    """Preserve rule bytes before editing; no policy judgment or Wiki write."""
    if scope not in {"maintenance", "whole-all"}:
        raise ValueError("unknown historical rule scope")
    base, root = Path(base).resolve(strict=True), Path(output_root).resolve()
    watched = ("cli/wiki", "wiki/rules", "agents/tp-wiki", "skills/wiki", "automation/wiki", "wiki/schema")
    if base.is_relative_to(root) or any(root.is_relative_to(base / name) for name in watched):
        raise ValueError("rule archive must be outside the Base rule directories and their ancestors")
    rules = current_rules(base, scope)
    if "cli/wiki/snapshot.py" not in rules:
        raise ValueError("Base snapshot implementation is missing")

    def stored_rules():
        for name in rules:
            path = root / name
            for entry in (path, *path.parents):
                if not entry.is_relative_to(root):
                    break
                info = entry.lstat()
                if (stat.S_ISLNK(info.st_mode) or getattr(info, "st_file_attributes", 0) & 0x400 or
                        (stat.S_ISREG(info.st_mode) and info.st_nlink > 1)):
                    raise ValueError("rule archive must contain independent bytes, not links or junctions")
        return historical_rules(base, old_root=root, scope=scope)[0]

    if root.exists():
        existing = stored_rules()
        if existing != rules:
            raise ValueError("existing rule archive differs; preserve it and choose another output root")
        status = "REUSED"
    else:
        # Read once and check against the inventory; never mix edits into an archive.
        contents = {name: (base / name).read_bytes() for name in rules}
        if {name: sha256_bytes(data) for name, data in contents.items()} != rules:
            raise ValueError("Base rules changed while preparing archive; retry after edits finish")
        root.mkdir(parents=True, exist_ok=False)
        for name, data in contents.items():
            path = root / name
            path.parent.mkdir(parents=True, exist_ok=True)
            with path.open("xb") as stream:
                stream.write(data)
        stored = stored_rules()
        if stored != rules:
            raise ValueError("rule archive verification failed; preserve the incomplete archive for diagnosis")
        status = "ARCHIVED"
    return {"status": status, "archive_root": str(root), "scope": scope,
            "file_count": len(rules), "rules_digest": _digest(rules), "rules": rules,
            "semantic_review_recorded": False}


def policy_review_hint(wiki_root, source_cfg):
    """Explain exact differences without treating them as semantic equivalence."""
    baseline = _read_json(snapshot_paths(wiki_root)["baseline"])
    if not baseline or baseline.get("maintenance_digest") == source_cfg.get("_maintenance_digest"):
        return None
    before, after = baseline.get("maintenance_components"), source_cfg["_maintenance_components"]
    known = (isinstance(before, dict) and before.get("format") == 1 and
             all(isinstance(before.get(k), dict) for k in ("configs", "rules")) and
             "cli/wiki/snapshot.py" in before["rules"])
    review = applicable_review(wiki_root, source_cfg)
    return {"status": "APPLICABLE" if review else "REVIEW_REQUIRED", "baseline_components_available": known,
            "changes": differences(before, after) if known else None,
            "baseline_digest": baseline.get("maintenance_digest"),
            "current_digest": source_cfg["_maintenance_digest"],
            "archive_lookup": "Read the matching Base delivery report for archive/evidence paths first; "
                              "check related report directories before declaring historical bytes missing.",
            "next_action": ("Existing policy review applies. Continue current source/subject/topology obligations and deterministic finalize."
                            if review else "Review actual differences, reproduce the baseline digest from complete old rule bytes "
                            "and effective config, then use wiki policy-review --old-base-root <archive> "
                            "--old-rule-scope <matching-scope> --summary <actual-review> --evidence-file <evidence>. "
                            "A partial before directory must be completed only with hash-matching unchanged bytes."),
            "evidence_limitations": [] if known else ["Baseline has no complete component inventory; do not infer old bytes."],
            "automatic_equivalence": False, "baseline_advanced": False}


def components(config, rules):
    return {"format": 1, "configs": {k: _digest(v) for k, v in config.items()}, "rules": rules}


def differences(before, after):
    return {group: [{"path": k, "before": before[group].get(k), "after": after[group].get(k)}
                    for k in sorted(set(before[group]) | set(after[group]))
                    if before[group].get(k) != after[group].get(k)]
            for group in ("configs", "rules")}


def prior_audit(baseline):
    completion = baseline.get("completion") or {}
    return completion.get("audit") or (completion.get("semantic_reuse") or {}).get("audit") or {}


def baseline_identity(baseline):
    return {**{k: baseline.get(k) for k in ("repo_id", "snapshot_id", "source", "maintenance_digest")},
            "subject_digest": (baseline.get("completion") or {}).get("subject_digest"),
            "audit_digest": _digest(prior_audit(baseline))}


def content_identity(wiki_root, change_set_id=None):
    """Normalize two clock scalars and the exact bound transaction ID only."""
    digest = hashlib.sha256()
    for path in sorted(p for p in wiki_root.rglob("*") if p.is_file()):
        rel = path.relative_to(wiki_root).as_posix()
        if rel.startswith("meta/") and path.name in _VOLATILE_META_NAMES:
            continue
        data = path.read_bytes()
        if rel == "meta/wiki-manifest.yaml":
            text, spans = data.decode("utf-8"), []
            document = yaml.compose(text)
            for keys in (("generated_at",), ("provenance", "manifest_refresh", "refreshed_at"), ("source_change_set_id",)):
                node = document
                for key in keys:
                    node = next((v for k, v in node.value if k.value == key), None) if isinstance(node, yaml.MappingNode) else None
                if isinstance(node, yaml.ScalarNode) and (keys != ("source_change_set_id",) or node.value == change_set_id):
                    spans.append((node.start_mark.index, node.end_mark.index))
            for start, end in sorted(spans, reverse=True):
                text = text[:start] + '"<machine-clock>"' + text[end:]
            data = text.encode("utf-8")
        digest.update(rel.encode("utf-8") + b"\0" + hashlib.sha256(data).digest() + b"\n")
    return digest.hexdigest()


def trusted_semantics(baseline):
    completion, audit = baseline.get("completion") or {}, prior_audit(baseline)
    verification = completion.get("verification") or {}
    if (completion.get("status") != "SUCCESS" or verification.get("result") != "PASS" or
            verification.get("subject_digest") != completion.get("subject_digest") or
            not isinstance(verification.get("semantic_audit_required"), bool)):
        return False
    if completion.get("audit"):
        return (audit.get("result") == "PASS" and audit.get("source") == baseline.get("source") and
                audit.get("subject_digest") == completion.get("subject_digest"))
    if not completion.get("semantic_reuse"):
        return verification["semantic_audit_required"] is False
    try:
        reuse, verification = completion["semantic_reuse"], completion["verification"]
        prior = {**reuse["baseline"], "completion": reuse["prior_completion"]}
        review = reuse["policy_review"]
        return (trusted_semantics(prior) and prior.get("source") == baseline.get("source") and
            audit == prior_audit(prior) and
            review["baseline"] == baseline_identity(prior) and _digest(audit) == review["baseline"]["audit_digest"] and
            review["subject"]["full_digest"] == review["baseline"]["subject_digest"] and
            review["subject"]["content_identity"] == reuse["content_identity"] and
            _digest({**review["config"], "rules": review["before"]["rules"]}) == prior.get("maintenance_digest") and
            _digest({**review["config"], "rules": review["after"]["rules"]}) == baseline.get("maintenance_digest") and
            review["before"]["configs"] == review["after"]["configs"] and
            review["changes"] == differences(review["before"], review["after"]) and
            verification.get("result") == "PASS" and verification.get("semantic_audit_required") is False and
            verification.get("subject_digest") == completion.get("subject_digest") and
            verification.get("policy_review_digest") == _digest(review))
    except (KeyError, TypeError):
        return False


def trustworthy_baseline(wiki_root, baseline):
    paths = snapshot_paths(wiki_root)
    return (trusted_semantics(baseline) and
            all(_read_json(paths[k]).get("result") != "FAIL" for k in ("verification", "audit")))


def historical_rules(base, *, old_root=None, old_ref=None, scope):
    if scope not in {"whole-all", "maintenance"}:
        raise ValueError("an explicit historical rule scope is required")
    if old_ref:
        def git(*args):
            return subprocess.run(["git", "-C", str(base), *args], check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE).stdout
        commit = git("rev-parse", "--verify", "--end-of-options", old_ref + "^{commit}").decode().strip()
        names = git("ls-tree", "-r", "--name-only", commit).decode("utf-8").splitlines()
        rules = {name: sha256_bytes(git("show", commit + ":" + name)) for name in names if selected_rule(name, scope)}
        origin = {"git_commit": commit, "scope": scope}
    else:
        root = Path(old_root).resolve(strict=True)
        rules = {p.relative_to(root).as_posix(): sha256_bytes(p.read_bytes()) for p in root.rglob("*")
                 if p.is_file() and selected_rule(p.relative_to(root).as_posix(), scope)}
        origin = {"archive_root": str(root), "scope": scope}
    if "cli/wiki/snapshot.py" not in rules:
        raise ValueError("historical Base snapshot implementation is missing")
    return rules, origin


def record_policy_review(wiki_root, source_cfg, *, old_root=None, old_ref=None, scope, summary, evidence_file):
    """Record the executor's semantic-equivalence judgment, not an L4 PASS."""
    if bool(old_root) == bool(old_ref) or not summary.strip():
        raise ValueError("choose one historical Base source and supply the actual review summary")
    evidence = Path(evidence_file).resolve(strict=True)
    if not evidence.is_file() or not evidence.read_bytes().strip():
        raise ValueError("policy review requires a non-empty actual evidence file")
    baseline = _read_json(snapshot_paths(wiki_root)["baseline"])
    if not trustworthy_baseline(wiki_root, baseline):
        raise ValueError("policy review requires successful baseline with explicit valid verification/audit obligations and no failed validation")
    rules, origin = historical_rules(Path(__file__).resolve().parents[2], old_root=old_root, old_ref=old_ref, scope=scope)
    config = source_cfg["_maintenance_config"]
    old_digest = _digest({**config, "rules": rules})
    if old_digest != baseline.get("maintenance_digest"):
        raise ValueError("historical rules plus effective configuration do not reproduce baseline maintenance_digest; "
                         "check the historical Base bytes, --old-rule-scope and effective configuration. "
                         "Current daily maintenance uses maintenance scope; whole-all is valid only for a matching historical baseline. "
                         "The scope is never switched automatically")
    before, after = components(config, rules), source_cfg["_maintenance_components"]
    if baseline.get("maintenance_components") and baseline["maintenance_components"] != before:
        raise ValueError("historical components disagree with recorded baseline components")
    manifest = yaml.safe_load((wiki_root / "meta/wiki-manifest.yaml").read_bytes()) or {}
    old_change_set_id = manifest.get("source_change_set_id")
    review = {"schema": "tp-spec.wiki-policy-review/v1", "recorded_at": utc_now(),
              "impact": "DETERMINISTIC_ONLY", "baseline": baseline_identity(baseline),
              "before": before, "after": after, "maintenance_digest": source_cfg["_maintenance_digest"],
              "config": config,
              "subject": {"full_digest": wiki_subject_digest(wiki_root), "manifest_change_set_id": old_change_set_id,
                          "content_identity": content_identity(wiki_root, old_change_set_id)},
              "changes": differences(before, after), "historical_source": origin,
              "summary": summary.strip(), "evidence": {"path": str(evidence), "sha256": sha256_bytes(evidence.read_bytes())}}
    _write_json(snapshot_paths(wiki_root)["policy_review"], review)
    return review


def applicable_review(wiki_root, source_cfg=None):
    if source_cfg is None:
        return None
    paths = snapshot_paths(wiki_root)
    baseline, pending = _read_json(paths["baseline"]), _read_json(paths["pending"])
    review = _read_json(paths["policy_review"])
    current = source_cfg.get("_maintenance_components") if source_cfg is not None else pending.get("maintenance_components")
    digest = source_cfg.get("_maintenance_digest") if source_cfg is not None else pending.get("maintenance_digest")
    try:
        config = review["before"]["configs"]
        if (review.get("impact") != "DETERMINISTIC_ONLY" or not review.get("summary", "").strip() or
                not trustworthy_baseline(wiki_root, baseline) or review.get("baseline") != baseline_identity(baseline) or
                review["after"] != current or review["maintenance_digest"] != digest or
                config != current["configs"] or review["changes"] != differences(review["before"], current) or
                components(review["config"], review["before"]["rules"]) != review["before"] or
                _digest({**review["config"], "rules": review["before"]["rules"]}) != baseline.get("maintenance_digest") or
                sha256_bytes(Path(review["evidence"]["path"]).read_bytes()) != review["evidence"]["sha256"]):
            return None
    except (KeyError, TypeError, OSError):
        return None
    return review


def semantic_refresh_reasons(wiki_root, changeset, source_cfg=None):
    reasons = list(changeset.get("refresh_reasons") or [])
    if "WIKI_SUBJECT_CHANGED" in reasons:
        from .subject import subject_scope
        if subject_scope(wiki_root, changeset)["status"] in {"EXACT", "MACHINE_ONLY"}:
            reasons.remove("WIKI_SUBJECT_CHANGED")
    review = applicable_review(wiki_root, source_cfg) if "MAINTENANCE_POLICY_CHANGED" in reasons else None
    if review:
        reasons.remove("MAINTENANCE_POLICY_CHANGED")
        # Expected incremental edits are covered by source-affected L4; a policy-only
        # run may not turn unrelated durable Wiki edits into an unaudited baseline.
        semantic_source = any(c.get("kind") in {"SEMANTIC", "STRUCTURAL", "DELETED", "UNCERTAIN"}
                              for c in changeset.get("changes", []))
        baseline = _read_json(snapshot_paths(wiki_root)["baseline"])
        subject = (baseline.get("completion") or {}).get("subject_digest")
        clocks_only = (review["subject"]["full_digest"] == subject and
                       review["subject"]["content_identity"] == content_identity(wiki_root, changeset.get("change_set_id")))
        if not semantic_source and subject != wiki_subject_digest(wiki_root) and not clocks_only:
            if "WIKI_SUBJECT_CHANGED" not in reasons:
                reasons.append("WIKI_SUBJECT_CHANGED")
    return reasons


def review_digest(wiki_root, source_cfg):
    review = applicable_review(wiki_root, source_cfg)
    return _digest(review) if review else None
