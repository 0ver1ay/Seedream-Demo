from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any


def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")


def _task_id() -> str:
    return f"task_{uuid.uuid4().hex[:10]}"


def normalize_task_prompts(raw: Any) -> list[dict[str, Any]]:
    if not isinstance(raw, list):
        return []
    out: list[dict[str, Any]] = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        tid = str(item.get("id") or _task_id())
        name = str(item.get("name") or "Задача").strip() or "Задача"
        prompt = str(item.get("prompt") or "")
        enhanced = str(item.get("prompt_enhanced") or "")
        iterations = item.get("iterations")
        if not isinstance(iterations, list):
            iterations = []
        clean_iters: list[dict[str, Any]] = []
        for it in iterations[-40:]:
            if not isinstance(it, dict):
                continue
            clean_iters.append(
                {
                    "at": str(it.get("at") or _now()),
                    "prompt": str(it.get("prompt") or ""),
                    "prompt_enhanced": str(it.get("prompt_enhanced") or ""),
                    "kind": str(it.get("kind") or "edit"),
                }
            )
        out.append(
            {
                "id": tid,
                "name": name,
                "prompt": prompt,
                "prompt_enhanced": enhanced,
                "updated_at": str(item.get("updated_at") or _now()),
                "iterations": clean_iters,
            }
        )
    return out


def create_task_prompt(*, name: str, prompt: str, prompt_enhanced: str = "") -> dict[str, Any]:
    now = _now()
    return {
        "id": _task_id(),
        "name": (name or "Задача").strip() or "Задача",
        "prompt": prompt or "",
        "prompt_enhanced": prompt_enhanced or "",
        "updated_at": now,
        "iterations": [
            {
                "at": now,
                "prompt": prompt or "",
                "prompt_enhanced": prompt_enhanced or "",
                "kind": "create",
            }
        ],
    }


def append_task_iteration(
    task: dict[str, Any],
    *,
    prompt: str,
    prompt_enhanced: str = "",
    kind: str = "edit",
) -> dict[str, Any]:
    now = _now()
    task["prompt"] = prompt or ""
    task["prompt_enhanced"] = prompt_enhanced or ""
    task["updated_at"] = now
    iters = task.setdefault("iterations", [])
    if not isinstance(iters, list):
        iters = []
        task["iterations"] = iters
    iters.append(
        {
            "at": now,
            "prompt": prompt or "",
            "prompt_enhanced": prompt_enhanced or "",
            "kind": kind,
        }
    )
    task["iterations"] = iters[-40:]
    return task


def find_task(tasks: list[dict[str, Any]], task_id: str | None) -> dict[str, Any] | None:
    if not task_id:
        return None
    for task in tasks:
        if str(task.get("id")) == task_id:
            return task
    return None
