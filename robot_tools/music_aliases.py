"""Conservative music-name equivalences shared by cloud tools and device matching."""
from __future__ import annotations

import json
import os
import re
import tempfile
from pathlib import Path
from threading import RLock

import yaml

ROOT = Path(__file__).resolve().parents[1]
CURATED = ROOT / "configs/music_aliases.yaml"
LEARNED = ROOT / "private/runtime/music_aliases.learned.json"
_LOCK = RLock()


def normalize(value: str) -> str:
    return re.sub(r"[^0-9a-zA-Z\u4e00-\u9fff]+", "", str(value).casefold())


def _valid_name(value: str) -> bool:
    return (isinstance(value, str) and 2 <= len(value.strip()) <= 60
            and bool(normalize(value)) and "\n" not in value
            and not any(c in value for c in "/\\<>\x00"))


def load_aliases() -> dict:
    with _LOCK:
        curated = yaml.safe_load(CURATED.read_text(encoding="utf-8")) or {}
        try:
            learned = json.loads(LEARNED.read_text(encoding="utf-8"))
        except (FileNotFoundError, ValueError):
            learned = {}
        merged = {"artists": {}, "songs": {}}
        for source in (curated, learned):
            for kind in merged:
                entries = source.get(kind, {}) if isinstance(source, dict) else {}
                if not isinstance(entries, dict):
                    continue
                for canonical, aliases in entries.items():
                    if not _valid_name(canonical) or not isinstance(aliases, list):
                        continue
                    values = merged[kind].setdefault(canonical.strip(), [])
                    for alias in aliases:
                        if _valid_name(alias) and alias.strip() not in values:
                            values.append(alias.strip())
        return merged


def equivalent(kind: str, requested: str, displayed: str) -> bool:
    """Only exact normalized names or configured aliases count as equivalence."""
    if kind not in ("artists", "songs"):
        return False
    left, right = normalize(requested), normalize(displayed)
    if not left or not right:
        return False
    if left == right:
        return True
    for canonical, aliases in load_aliases()[kind].items():
        variants = {normalize(item) for item in [canonical, *aliases]}
        if left in variants and right in variants:
            return True
    return False


def add_alias(kind: str, canonical: str, alias: str, evidence: str) -> dict:
    """Persist a model-discovered name in private runtime data after validation."""
    if kind not in ("artists", "songs") or not all(map(_valid_name, (canonical, alias))):
        return {"ok": False, "status": "rejected", "reason": "invalid_name"}
    if not isinstance(evidence, str) or not 8 <= len(evidence.strip()) <= 300:
        return {"ok": False, "status": "rejected", "reason": "missing_evidence"}
    if (normalize(canonical) not in normalize(evidence)
            or normalize(alias) not in normalize(evidence)):
        return {"ok": False, "status": "rejected", "reason": "names_missing_in_evidence"}
    if normalize(canonical) == normalize(alias):
        return {"ok": False, "status": "rejected", "reason": "same_name"}
    with _LOCK:
        existing = load_aliases()
        if any(equivalent(kind, alias, name) for name in existing[kind]
               if name != canonical):
            return {"ok": False, "status": "rejected", "reason": "conflicting_alias"}
        if equivalent(kind, canonical, alias):
            return {"ok": True, "status": "already_present", "executed": False}
        try:
            data = json.loads(LEARNED.read_text(encoding="utf-8"))
        except (FileNotFoundError, ValueError):
            data = {}
        if not isinstance(data, dict):
            data = {}
        section = data.setdefault(kind, {})
        section.setdefault(canonical.strip(), []).append(alias.strip())
        data.setdefault("evidence", {})[
            f"{kind}:{canonical.strip()}:{alias.strip()}"] = evidence.strip()
        LEARNED.parent.mkdir(parents=True, exist_ok=True)
        fd, temporary = tempfile.mkstemp(prefix="music-alias-", dir=LEARNED.parent)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as stream:
                json.dump(data, stream, ensure_ascii=False, indent=2)
            os.replace(temporary, LEARNED)
        finally:
            if os.path.exists(temporary):
                os.unlink(temporary)
    return {"ok": True, "status": "saved", "executed": True,
            "kind": kind, "canonical": canonical.strip(), "alias": alias.strip()}
