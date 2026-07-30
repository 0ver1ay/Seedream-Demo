from __future__ import annotations

import base64
import copy
import hashlib
import os
import re
import uuid
from datetime import datetime
from typing import Any

from seedream_desktop.io_utils import load_json_file, save_json_file
from seedream_desktop.models import (
    ASSETS_DIRNAME,
    PROJECT_SCHEMA_VERSION,
    REFS_SUBDIR,
    RefItem,
    guess_mime_type,
)


def _entity_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:12]}"


def _slugify(name: str, fallback: str) -> str:
    raw = (name or "").strip().lower()
    raw = re.sub(r"[^\w\-\u0400-\u04FF]+", "_", raw, flags=re.UNICODE)
    raw = raw.strip("_")[:48]
    return raw or fallback


def _unique_slug(base: str, existing: set[str]) -> str:
    slug = base or "branch"
    if slug not in existing:
        existing.add(slug)
        return slug
    n = 2
    while f"{slug}_{n}" in existing:
        n += 1
    out = f"{slug}_{n}"
    existing.add(out)
    return out


def _empty_branch_dict(
    *,
    branch_id: str,
    name: str,
    slug: str,
    parent_branch_id: str | None,
) -> dict[str, Any]:
    return {
        "id": branch_id,
        "name": name,
        "slug": slug,
        "parent_branch_id": parent_branch_id,
        "created_at": datetime.now().isoformat(timespec="seconds"),
        "autosave_dir": "",
        "prompt_snapshot": "",
        "prompt_enhanced_snapshot": "",
        "use_enhanced": 0,
        "refs_snapshot": [],
        "gen_snapshot": {},
        "images": [],
        "runs": [],
    }


def _empty_stage_dict(stage_id: str, name: str, slug: str, branch: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": stage_id,
        "name": name,
        "slug": slug,
        "branches": [branch],
        "active_branch_id": branch["id"],
    }


def _empty_pipeline_dict(pipeline_id: str, name: str, slug: str, stage: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": pipeline_id,
        "name": name,
        "slug": slug,
        "stages": [stage],
        "active_stage_id": stage["id"],
    }


def default_pipelines_bundle() -> tuple[list[dict[str, Any]], str, str, str]:
    pid, sid, bid = _entity_id("pip"), _entity_id("stg"), _entity_id("br")
    branch = _empty_branch_dict(branch_id=bid, name="main", slug="main", parent_branch_id=None)
    stage = _empty_stage_dict(sid, "Концепт", "concept", branch)
    pipe = _empty_pipeline_dict(pid, "Окружение", "environment", stage)
    return [pipe], pid, sid, bid


def repair_pipeline_invariants(
    pipelines: list[dict[str, Any]],
    active_pipeline_id: str | None,
    active_stage_id: str | None,
    active_branch_id: str | None,
) -> tuple[list[dict[str, Any]], str, str, str]:
    if not pipelines:
        return default_pipelines_bundle()
    for pipe in pipelines:
        if not pipe.get("slug"):
            pipe["slug"] = _slugify(str(pipe.get("name") or "pipeline"), "pipeline")
        stages = pipe.setdefault("stages", [])
        if not stages:
            bid = _entity_id("br")
            br = _empty_branch_dict(bid, "main", "main", None)
            sid = _entity_id("stg")
            stages.append(_empty_stage_dict(sid, "Этап 1", "stage_1", br))
            pipe["active_stage_id"] = sid
        for st in stages:
            if not st.get("slug"):
                st["slug"] = _slugify(str(st.get("name") or "stage"), "stage")
            brs = st.setdefault("branches", [])
            if not brs:
                bid = _entity_id("br")
                brs.append(_empty_branch_dict(bid, "main", "main", None))
                st["active_branch_id"] = bid
            for br in brs:
                if not br.get("slug"):
                    br["slug"] = _slugify(str(br.get("name") or "branch"), "branch")
                br.setdefault("images", [])
                br.setdefault("runs", [])
                br.setdefault("refs_snapshot", [])
                br.setdefault("gen_snapshot", {})
                br.setdefault("created_at", datetime.now().isoformat(timespec="seconds"))
                br.setdefault("autosave_dir", "")
    pids = [str(p.get("id")) for p in pipelines if p.get("id")]
    if not pids or active_pipeline_id not in pids:
        active_pipeline_id = str(pipelines[0].get("id") or "")
    pipe = next((p for p in pipelines if p.get("id") == active_pipeline_id), pipelines[0])
    stages = pipe.get("stages") or []
    sids = [str(s.get("id")) for s in stages if s.get("id")]
    if not sids or active_stage_id not in sids:
        active_stage_id = str(stages[0].get("id") or "")
    pipe["active_stage_id"] = active_stage_id
    stage = next((s for s in stages if s.get("id") == active_stage_id), stages[0])
    branches = stage.get("branches") or []
    bids = [str(b.get("id")) for b in branches if b.get("id")]
    if not bids or active_branch_id not in bids:
        active_branch_id = str(branches[0].get("id") or "")
    stage["active_branch_id"] = active_branch_id
    return pipelines, active_pipeline_id, active_stage_id, active_branch_id


def _ref_storage_path(workspace_root: str, name: str, raw: bytes) -> str:
    digest = hashlib.sha256(raw).hexdigest()[:16]
    safe_name = re.sub(r"[^\w\-.]+", "_", os.path.basename(name))[:80] or "ref"
    refs_dir = os.path.join(workspace_root, REFS_SUBDIR)
    os.makedirs(refs_dir, exist_ok=True)
    rel = f"{REFS_SUBDIR}/{digest}_{safe_name}"
    abs_path = os.path.join(workspace_root, rel.replace("/", os.sep))
    if not os.path.isfile(abs_path):
        with open(abs_path, "wb") as f:
            f.write(raw)
    return rel.replace("\\", "/")


def materialize_ref(ref: RefItem, workspace_root: str) -> RefItem:
    if ref.rel_path:
        return ref
    if not ref.base64:
        return ref
    raw = base64.b64decode(ref.base64)
    rel = _ref_storage_path(workspace_root, ref.name, raw)
    return RefItem(name=ref.name, mime=ref.mime, rel_path=rel)


def materialize_refs(refs: list[RefItem], workspace_root: str) -> list[RefItem]:
    os.makedirs(workspace_root, exist_ok=True)
    return [materialize_ref(r, workspace_root) for r in refs]


def refs_to_snapshot(refs: list[RefItem], workspace_root: str) -> list[dict[str, Any]]:
    return [materialize_ref(r, workspace_root).to_dict() for r in refs]


def migrate_legacy_pipelines(payload: dict[str, Any]) -> tuple[list[dict[str, Any]], str, str, str]:
    pipelines, ap, ast, ab = default_pipelines_bundle()
    pipe = pipelines[0]
    stage = (pipe.get("stages") or [None])[0]
    branch = (stage.get("branches") or [None])[0] if stage else None
    if branch is None:
        return pipelines, ap, ast, ab
    branch["prompt_snapshot"] = str(payload.get("prompt") or "")
    branch["prompt_enhanced_snapshot"] = str(payload.get("prompt_enhanced") or "")
    branch["use_enhanced"] = int(payload.get("use_enhanced", 0) or 0)
    refs = []
    for item in payload.get("refs", []) or []:
        if isinstance(item, dict) and item.get("base64"):
            refs.append(
                {
                    "name": str(item.get("name") or "reference"),
                    "base64": item["base64"],
                    "mime": str(item.get("mime") or guess_mime_type(str(item.get("name") or ""))),
                }
            )
    branch["refs_snapshot"] = refs
    return pipelines, ap, ast, ab


def migrate_branch_refs_to_files(
    pipelines: list[dict[str, Any]],
    workspace_root: str,
) -> None:
    for pipe in pipelines:
        for stage in pipe.get("stages") or []:
            for branch in stage.get("branches") or []:
                refs_in = branch.get("refs_snapshot") or []
                out: list[dict[str, Any]] = []
                for item in refs_in:
                    ref = RefItem.from_dict(item) if isinstance(item, dict) else None
                    if ref is None:
                        continue
                    out.append(materialize_ref(ref, workspace_root).to_dict())
                branch["refs_snapshot"] = out


def load_pipelines_from_payload(
    payload: dict[str, Any],
    workspace_root: str,
) -> tuple[list[dict[str, Any]], str, str, str]:
    raw = payload.get("pipelines")
    if isinstance(raw, list) and len(raw) > 0:
        pipelines = copy.deepcopy(raw)
        ap = str(payload.get("active_pipeline_id") or pipelines[0].get("id") or "")
        ast = str(payload.get("active_stage_id") or "")
        ab = str(payload.get("active_branch_id") or "")
    else:
        pipelines, ap, ast, ab = migrate_legacy_pipelines(payload)
    pipelines, ap, ast, ab = repair_pipeline_invariants(pipelines, ap, ast, ab)
    version = int(payload.get("seedream_project_version") or 2)
    if version < PROJECT_SCHEMA_VERSION:
        migrate_branch_refs_to_files(pipelines, workspace_root)
    return pipelines, ap, ast, ab


def normalize_project_payload(
    payload: dict[str, Any],
    *,
    workspace_root: str,
    top_level_refs: list[RefItem] | None = None,
) -> dict[str, Any]:
    pipelines, ap, ast, ab = load_pipelines_from_payload(payload, workspace_root)
    if top_level_refs is not None:
        branch = None
        for pipe in pipelines:
            if pipe.get("id") != ap:
                continue
            for stage in pipe.get("stages") or []:
                if stage.get("id") != ast:
                    continue
                for br in stage.get("branches") or []:
                    if br.get("id") == ab:
                        branch = br
                        break
        if branch is not None:
            branch["refs_snapshot"] = refs_to_snapshot(top_level_refs, workspace_root)
    out = copy.deepcopy(payload)
    out["seedream_project_version"] = PROJECT_SCHEMA_VERSION
    out["pipelines"] = pipelines
    out["active_pipeline_id"] = ap
    out["active_stage_id"] = ast
    out["active_branch_id"] = ab
    out["autosave_root_path"] = workspace_root
    out["refs"] = refs_to_snapshot(top_level_refs or [], workspace_root)
    return out


def default_workspace_root(app_dir: str) -> str:
    return os.path.normpath(os.path.join(app_dir, ASSETS_DIRNAME))


def branch_rel_prefix(pipe: dict[str, Any], stage: dict[str, Any], branch: dict[str, Any]) -> str:
    return os.path.join(
        "pipelines",
        str(pipe.get("slug") or "pipeline"),
        str(stage.get("slug") or "stage"),
        str(branch.get("slug") or "branch"),
    ).replace("\\", "/")


def write_branch_sidecar(workspace_root: str, pipe: dict[str, Any], stage: dict[str, Any], branch: dict[str, Any]) -> None:
    rel_prefix = branch_rel_prefix(pipe, stage, branch)
    branch["autosave_dir"] = rel_prefix
    folder = os.path.normpath(os.path.join(workspace_root, rel_prefix.replace("/", os.sep)))
    os.makedirs(folder, exist_ok=True)
    side = {
        "branch_id": branch.get("id"),
        "name": branch.get("name"),
        "slug": branch.get("slug"),
        "parent_branch_id": branch.get("parent_branch_id"),
        "created_at": branch.get("created_at"),
        "autosave_dir": branch.get("autosave_dir"),
        "images": branch.get("images"),
        "runs": branch.get("runs"),
    }
    save_json_file(os.path.join(folder, "branch.json"), side)
