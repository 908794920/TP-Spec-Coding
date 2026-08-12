# -*- coding: utf-8 -*-
"""Source discovery and semantic fingerprinting.

Raw fingerprints capture byte identity. Normalized fingerprints intentionally
ignore selected cosmetic differences while preserving language-significant
structure (notably Python/YAML indentation).
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any, Dict, Iterable, List, Optional, Tuple
import fnmatch
import hashlib
import io
import re
import tokenize
import unicodedata


@dataclass(frozen=True)
class FileFingerprint:
    path: str
    size: int
    mtime_ns: int
    content_hash: str
    normalized_hash: str
    encoding: str
    decode_status: str

    def as_dict(self) -> Dict[str, Any]:
        return {
            "size": self.size,
            "mtime_ns": self.mtime_ns,
            "content_hash": self.content_hash,
            "normalized_hash": self.normalized_hash,
            "encoding": self.encoding,
            "decode_status": self.decode_status,
        }


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def decode_text(data: bytes) -> Tuple[Optional[str], str, str]:
    # BOM-aware decoding first. This makes a checkout/export that changes only the
    # Unicode storage encoding (UTF-8/UTF-16) normalize to the same semantic text.
    for bom, encoding, codec in (
        (b"\xef\xbb\xbf", "utf-8-sig", "utf-8-sig"),
        (b"\xff\xfe\x00\x00", "utf-32-le", "utf-32"),
        (b"\x00\x00\xfe\xff", "utf-32-be", "utf-32"),
        (b"\xff\xfe", "utf-16-le", "utf-16"),
        (b"\xfe\xff", "utf-16-be", "utf-16"),
    ):
        if data.startswith(bom):
            try:
                return data.decode(codec), encoding, "certain"
            except UnicodeDecodeError:
                break
    try:
        text = data.decode("utf-8")
        # A BOM-less UTF-16 file made mostly from ASCII can technically decode as
        # UTF-8 while containing many NULs. Treat that as ambiguous rather than
        # silently fingerprinting mojibake.
        if text and text.count("\x00") / max(1, len(text)) > 0.10:
            return None, "unknown", "uncertain"
        return text, "utf-8", "certain"
    except UnicodeDecodeError:
        pass
    # gb18030 covers GBK/GB2312 and is common in legacy Chinese Java projects.
    try:
        text = data.decode("gb18030")
        if text and text.count("\x00") / max(1, len(text)) > 0.10:
            return None, "unknown", "uncertain"
        return text, "gb18030", "fallback"
    except UnicodeDecodeError:
        return None, "unknown", "uncertain"


def _base_lines(text: str, *, preserve_leading: bool) -> List[str]:
    text = unicodedata.normalize("NFC", text).replace("\r\n", "\n").replace("\r", "\n")
    out: List[str] = []
    for line in text.split("\n"):
        line = line.rstrip()
        candidate = line if preserve_leading else line.strip()
        if candidate.strip():
            out.append(candidate)
    return out


def _normalize_python(text: str) -> str:
    try:
        tokens = []
        reader = io.StringIO(text.replace("\r\n", "\n").replace("\r", "\n")).readline
        for tok in tokenize.generate_tokens(reader):
            if tok.type in {tokenize.ENCODING, tokenize.COMMENT, tokenize.NL, tokenize.NEWLINE, tokenize.ENDMARKER}:
                continue
            # INDENT/DEDENT remain, so indentation-sensitive semantics are preserved.
            tokens.append(f"{tok.type}:{tok.string}")
        return "\n".join(tokens)
    except (tokenize.TokenError, IndentationError):
        return "\n".join(_base_lines(text, preserve_leading=True))


def _strip_c_style_comments(text: str) -> str:
    """Remove // and /* */ comments while preserving quoted string/char content.

    This is intentionally conservative: it avoids the old regex bug where a string such
    as "http://host" was truncated and a real string-value change could be misclassified
    as cosmetic.
    """
    out: List[str] = []
    i = 0
    state = "code"
    quote = ""
    while i < len(text):
        ch = text[i]
        nxt = text[i + 1] if i + 1 < len(text) else ""
        if state == "code":
            if ch in {'"', "'", "`"}:
                state = "string"
                quote = ch
                out.append(ch)
                i += 1
                continue
            if ch == "/" and nxt == "/":
                state = "line_comment"
                i += 2
                continue
            if ch == "/" and nxt == "*":
                state = "block_comment"
                i += 2
                continue
            out.append(ch)
            i += 1
            continue
        if state == "string":
            out.append(ch)
            if ch == "\\" and i + 1 < len(text):
                out.append(text[i + 1])
                i += 2
                continue
            if ch == quote:
                state = "code"
            i += 1
            continue
        if state == "line_comment":
            if ch in "\r\n":
                out.append(ch)
                state = "code"
            i += 1
            continue
        if state == "block_comment":
            if ch == "*" and nxt == "/":
                state = "code"
                i += 2
            else:
                # Preserve newlines so tokens/lines around comments do not concatenate.
                if ch in "\r\n":
                    out.append(ch)
                i += 1
    return "".join(out)


def normalize_text(path: str, text: str, properties_mode: str = "keys") -> str:
    ext = Path(path).suffix.lower()
    text = unicodedata.normalize("NFC", text)
    if ext == ".py":
        return _normalize_python(text)
    if ext == ".java":
        return "\n".join(_base_lines(_strip_c_style_comments(text), preserve_leading=False))
    if ext == ".vue":
        # Vue mixes HTML/JS/CSS; without a full parser only remove HTML comments.
        # Script/style text remains intact so a real change can never disappear as
        # an accidental "cosmetic" classification.
        text = re.sub(r"<!--.*?-->", "", text, flags=re.S)
        return "\n".join(_base_lines(text, preserve_leading=True))
    if ext == ".xml":
        text = re.sub(r"<!--.*?-->", "", text, flags=re.S)
        return "\n".join(_base_lines(text, preserve_leading=True))
    if ext in {".yaml", ".yml"}:
        # YAML indentation is semantic; only full-line comments/trailing whitespace are cosmetic.
        text = re.sub(r"(?m)^[ \t]*#[^\r\n]*$", "", text)
        return "\n".join(_base_lines(text, preserve_leading=True))
    if ext == ".properties" and properties_mode == "keys":
        keys: List[str] = []
        for raw in text.replace("\r\n", "\n").replace("\r", "\n").split("\n"):
            line = raw.strip()
            if not line or line.startswith(("#", "!")):
                continue
            # Compatibility with the established snapshot policy: values are reference context;
            # key additions/removals remain semantic.
            indexes = [i for i in (line.find("="), line.find(":")) if i >= 0]
            idx = min(indexes) if indexes else -1
            keys.append((line[:idx] if idx > 0 else line).strip())
        return "\n".join(sorted(keys))
    if ext in {".md", ".sql", ".json", ".ps1", ".sh", ".cmd", ".bat"}:
        return "\n".join(_base_lines(text, preserve_leading=True))
    return "\n".join(_base_lines(text, preserve_leading=True))


def normalized_hash(path: str, data: bytes, properties_mode: str = "keys") -> Tuple[str, str, str]:
    text, encoding, status = decode_text(data)
    if text is None:
        return sha256_bytes(data), encoding, status
    normalized = normalize_text(path, text, properties_mode=properties_mode)
    return sha256_bytes(normalized.encode("utf-8")), encoding, status


def _is_excluded(rel: str, cfg: Dict[str, Any]) -> bool:
    parts = PurePosixPath(rel).parts
    excluded_segments = set(str(x) for x in cfg.get("exclude_segments", []))
    if any(part in excluded_segments for part in parts):
        return True
    for pattern in cfg.get("exclude_globs", []):
        if fnmatch.fnmatch(rel, str(pattern)) or fnmatch.fnmatch("/" + rel, str(pattern)):
            return True
    return False


def discover_source_files(repo_root: Path, cfg: Dict[str, Any]) -> List[str]:
    repo_root = repo_root.resolve(strict=False)
    extensions = {str(x).lower() for x in cfg.get("include_extensions", [])}
    names = {str(x) for x in cfg.get("include_names", [])}
    out: List[str] = []
    if not repo_root.is_dir():
        return out
    for p in repo_root.rglob("*"):
        if not p.is_file():
            continue
        try:
            rel = p.relative_to(repo_root).as_posix()
        except ValueError:
            continue
        if _is_excluded(rel, cfg):
            continue
        if p.name in names or p.suffix.lower() in extensions:
            out.append(rel)
    return sorted(set(out))




def resolve_repo_relative(repo_root: Path, rel: str) -> Path:
    """Resolve a manifest/citation source path inside repo_root.

    Wiki metadata is AI-authored input. Absolute paths and ``..`` traversal are
    rejected so quality/manifest refresh cannot accidentally read outside the
    registered source repository.
    """
    text = str(rel or "").replace("\\", "/").strip()
    pure = PurePosixPath(text)
    if not text or pure.is_absolute() or ".." in pure.parts:
        raise ValueError(f"unsafe repo-relative path: {rel!r}")
    root = repo_root.resolve(strict=False)
    candidate = (root / pure).resolve(strict=False)
    try:
        candidate.relative_to(root)
    except ValueError as exc:
        raise ValueError(f"path escapes repo root: {rel!r}") from exc
    return candidate

def fingerprint_file(repo_root: Path, rel: str, cfg: Dict[str, Any]) -> FileFingerprint:
    full = resolve_repo_relative(repo_root, rel)
    data = full.read_bytes()
    stat = full.stat()
    norm, encoding, decode_status = normalized_hash(rel, data, str(cfg.get("properties_normalization") or "keys"))
    return FileFingerprint(
        path=rel,
        size=stat.st_size,
        mtime_ns=stat.st_mtime_ns,
        content_hash=sha256_bytes(data),
        normalized_hash=norm,
        encoding=encoding,
        decode_status=decode_status,
    )
