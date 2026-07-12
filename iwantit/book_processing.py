"""Safe post-download normalization for ebook and audiobook releases."""

from __future__ import annotations

import json
import subprocess
from dataclasses import dataclass
from typing import Any


class BookProcessingError(RuntimeError):
    """A post-download processing operation failed."""


REMOTE_PROCESSOR = r'''
import json, os, re, shutil, subprocess, sys, tempfile, zipfile
from datetime import datetime, timezone
from pathlib import Path

ebook_root, audio_root, ingest_root, state_path, apply_value, min_mtime_value = sys.argv[1:7]
apply_changes = apply_value == "1"
min_mtime = float(min_mtime_value or 0)
ebook_root, audio_root, ingest_root = map(Path, (ebook_root, audio_root, ingest_root))
state_path = Path(state_path)
ebook_ext = {".epub", ".mobi", ".azw", ".azw3", ".pdf", ".djvu", ".fb2"}
audio_ext = {".m4b", ".m4a", ".mp3", ".flac", ".aac", ".ogg", ".opus"}
archive_ext = {".zip", ".rar", ".r00", ".7z"}
excluded = {"Calibre", "IWantIt Normalized", ".iwantit-processing"}
try:
    state = json.loads(state_path.read_text()) if state_path.exists() else {}
except Exception:
    state = {}
processed = state.setdefault("processed", {})
results = []

def signature(path):
    stat = path.stat()
    return f"{path}:{stat.st_size}:{stat.st_mtime_ns}"

def safe_name(value):
    value = re.sub(r"[^\w .,'()&+-]+", "_", value, flags=re.UNICODE).strip(" .")
    return value[:180] or "unknown"

def valid_epub(path):
    try:
        with zipfile.ZipFile(path) as archive:
            return archive.testzip() is None and "META-INF/container.xml" in archive.namelist()
    except Exception:
        return False

def valid_ebook(path):
    return path.stat().st_size > 0 and (path.suffix.lower() != ".epub" or valid_epub(path))

def copy_file(source, destination):
    destination.parent.mkdir(parents=True, exist_ok=True)
    if destination.exists() and destination.stat().st_size == source.stat().st_size:
        return
    shutil.copy2(source, destination)

def safe_unzip(source, destination):
    with zipfile.ZipFile(source) as archive:
        members = archive.infolist()
        if len(members) > 10000 or sum(item.file_size for item in members) > 2_000_000_000:
            raise ValueError("archive exceeds safe extraction limits")
        base = destination.resolve()
        for member in members:
            if (member.external_attr >> 16) & 0o170000 == 0o120000:
                raise ValueError("archive contains a symbolic link")
            target = (destination / member.filename).resolve()
            if target != base and base not in target.parents:
                raise ValueError("archive path traversal")
        archive.extractall(destination)

def extract_release(release):
    with tempfile.TemporaryDirectory(prefix="iwantit-book-") as temp_name:
        temp = Path(temp_name)
        archives = [p for p in release.rglob("*") if p.is_file() and p.suffix.lower() in archive_ext]
        for archive in sorted(archives):
            if archive.stat().st_size == 0:
                raise ValueError(f"zero-byte archive: {archive.name}")
            if archive.suffix.lower() == ".zip":
                safe_unzip(archive, temp)
        # Scene releases commonly wrap a RAR (or multipart RAR set) inside ZIPs.
        rar_files = sorted(temp.rglob("*.rar"))
        if not rar_files:
            rar_files = sorted(p for p in archives if p.suffix.lower() == ".rar")
        if rar_files:
            completed = subprocess.run(
                ["unrar", "x", "-o+", "-p-", str(rar_files[0]), str(temp / "unrar") + "/"],
                capture_output=True, text=True, check=False,
            )
            if completed.returncode not in {0, 1}:
                raise ValueError("RAR extraction failed or requires a password")
        outputs = [p for p in temp.rglob("*") if p.is_file() and p.suffix.lower() in ebook_ext and valid_ebook(p)]
        groups = {safe_name(p.stem).casefold() for p in outputs}
        if not outputs:
            raise ValueError("archive contains no valid ebook")
        if len(groups) > 3:
            raise ValueError("archive appears to contain a multi-book collection")
        copied = []
        if apply_changes:
            destination = ingest_root / safe_name(release.name)
            for output in outputs:
                target = destination / safe_name(output.name)
                copy_file(output, target)
                copied.append(str(target))
        return copied or [str(p) for p in outputs]

def copy_audio_release(release, audio_files):
    destination = audio_root / "IWantIt Recovered" / safe_name(release.name)
    copied = []
    if apply_changes:
        for source in audio_files:
            relative = source.relative_to(release) if release.is_dir() else Path(source.name)
            target = destination / relative
            copy_file(source, target)
            copied.append(str(target))
    return copied or [str(p) for p in audio_files]

for release in sorted(ebook_root.iterdir() if ebook_root.is_dir() else []):
    if release.name in excluded:
        continue
    files = [release] if release.is_file() else [p for p in release.rglob("*") if p.is_file()]
    if not files:
        continue
    if max(path.stat().st_mtime for path in files) < min_mtime:
        continue
    sig = "|".join(sorted(signature(path) for path in files))
    previous = processed.get(str(release))
    previous_signature = previous.get("signature") if isinstance(previous, dict) else previous
    if previous_signature == sig:
        if apply_changes and not isinstance(previous, dict):
            processed[str(release)] = {
                "signature": sig,
                "status": "processed",
                "processed_at": datetime.now(timezone.utc).isoformat(),
            }
        continue
    audio_files = [p for p in files if p.suffix.lower() in audio_ext and p.stat().st_size > 0]
    direct_ebooks = [p for p in files if p.suffix.lower() in ebook_ext and valid_ebook(p)]
    archives = [p for p in files if p.suffix.lower() in archive_ext]
    try:
        if re.search(r"[\u0400-\u04ff]", str(release)):
            raise ValueError("foreign-language release requires review")
        if audio_files and not direct_ebooks:
            outputs = copy_audio_release(release, audio_files)
            action = "audio_recovered"
        elif archives and not direct_ebooks:
            outputs = extract_release(release if release.is_dir() else release.parent)
            action = "archive_normalized"
        elif direct_ebooks:
            outputs = []
            if apply_changes:
                destination = ingest_root / safe_name(release.stem if release.is_file() else release.name)
                for source in direct_ebooks:
                    target = destination / safe_name(source.name)
                    copy_file(source, target)
                    outputs.append(str(target))
            else:
                outputs = [str(p) for p in direct_ebooks]
            action = "ebook_staged"
        else:
            continue
        results.append({"source": str(release), "status": action, "outputs": outputs})
        if apply_changes:
            processed[str(release)] = {
                "signature": sig, "status": action, "outputs": outputs,
                "processed_at": datetime.now(timezone.utc).isoformat(),
            }
    except Exception as exc:
        results.append({"source": str(release), "status": "quarantined", "reason": str(exc)})
        if apply_changes:
            # Remember the exact failed signature to avoid noisy repeated work.
            # A completed/replaced download changes the signature and is retried.
            processed[str(release)] = {
                "signature": sig, "status": "quarantined", "reason": str(exc),
                "processed_at": datetime.now(timezone.utc).isoformat(),
            }

if apply_changes:
    state_path.parent.mkdir(parents=True, exist_ok=True)
    state_path.write_text(json.dumps(state, indent=2, sort_keys=True))
print(json.dumps({"apply": apply_changes, "results": results}, ensure_ascii=False))
'''


@dataclass
class RemoteBookProcessor:
    config: dict[str, Any]

    def run(self, *, apply: bool = False) -> dict[str, Any]:
        section = self.config.get("book_processing") or {}
        host = str(section.get("ssh_host") or "").strip()
        required = ("ebook_root", "audiobook_root", "ebook_ingest_root", "state_path")
        missing = [key for key in required if not section.get(key)]
        if not host or missing:
            raise BookProcessingError(
                "book_processing requires ssh_host and " + ", ".join(required)
            )
        command = [
            "ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=10", host,
            "python3", "-",
            str(section["ebook_root"]), str(section["audiobook_root"]),
            str(section["ebook_ingest_root"]), str(section["state_path"]),
            "1" if apply else "0",
            str(section.get("min_mtime_epoch") or 0),
        ]
        completed = subprocess.run(
            command, input=REMOTE_PROCESSOR, capture_output=True, text=True,
            timeout=float(section.get("timeout", 600)), check=False,
        )
        if completed.returncode:
            raise BookProcessingError(
                (completed.stderr.strip().splitlines() or ["remote book processing failed"])[-1]
            )
        try:
            result = json.loads(completed.stdout)
        except json.JSONDecodeError as exc:
            raise BookProcessingError("remote book processor returned invalid JSON") from exc
        if not isinstance(result, dict):
            raise BookProcessingError("remote book processor returned an unexpected result")
        return result
