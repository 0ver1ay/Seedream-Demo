from __future__ import annotations

import base64
import os
from dataclasses import dataclass, field
from typing import Any

from server.core import DEFAULT_IMAGE_MODEL, IMAGE_MODEL_CONFIGS

PROJECT_SCHEMA_VERSION = 3
ASSETS_DIRNAME = "seedream_assets"
REFS_SUBDIR = "refs"

IMAGE_FILE_TYPES = [("Images", "*.png *.jpg *.jpeg *.webp"), ("All", "*.*")]
PROJECT_FILE_TYPES = [("Seedream project", "*.seedream.json"), ("JSON", "*.json")]

ENHANCE_MODELS = [
    "replicate:openai/gpt-5.4",
    "replicate:openai/gpt-5",
    "replicate:google/gemini-3-pro",
    "replicate:meta/llama-3.1-8b-instruct",
]

IMAGE_MODEL_LABEL_TO_SLUG = {
    config.get("label", slug): slug for slug, config in IMAGE_MODEL_CONFIGS.items()
}
IMAGE_MODEL_SLUG_TO_LABEL = {
    slug: config.get("label", slug) for slug, config in IMAGE_MODEL_CONFIGS.items()
}

# Человекочитаемые подписи формата (как в старой версии: 16:9, match_input_image, …)
ASPECT_RATIO_LABELS: dict[str, str] = {
    "match_input_image": "Как у референса",
    "1:1": "1:1 · Квадрат",
    "16:9": "16:9 · Широкий",
    "9:16": "9:16 · Вертикаль",
    "4:3": "4:3 · Классика",
    "3:4": "3:4 · Портрет",
    "3:2": "3:2 · Фото",
    "2:3": "2:3 · Портрет",
    "21:9": "21:9 · Ультраширокий",
    "4:5": "4:5 · Соцсети",
    "5:4": "5:4",
}
ASPECT_QUICK_PRESETS = ("match_input_image", "1:1", "16:9", "9:16", "4:3", "21:9")

SIZE_LABELS: dict[str, str] = {
    "512": "512px",
    "1K": "1K",
    "2K": "2K",
    "3K": "3K",
    "4K": "4K",
    "1 MP": "1 MP",
    "2 MP": "2 MP",
    "4 MP": "4 MP",
}


def aspect_label(value: str) -> str:
    return ASPECT_RATIO_LABELS.get(value, value)


def aspect_value_from_label(label: str) -> str:
    for value, text in ASPECT_RATIO_LABELS.items():
        if text == label:
            return value
    return label


def size_label(value: str) -> str:
    return SIZE_LABELS.get(value, value)


def preferred_size(sizes: list[str]) -> str:
    for candidate in ("4K", "3K", "2K", "2 MP", "1 MP", "4 MP", "1K", "512"):
        if candidate in sizes:
            return candidate
    return sizes[0] if sizes else "4K"


def preferred_aspect(aspects: list[str]) -> str:
    for candidate in ("match_input_image", "16:9", "1:1"):
        if candidate in aspects:
            return candidate
    return aspects[0] if aspects else "match_input_image"


ENHANCE_MODEL_SLUG_TO_LABEL = {
    "replicate:openai/gpt-5.4": "GPT-5.4 (vision)",
    "replicate:openai/gpt-5": "GPT-5 (vision)",
    "replicate:google/gemini-3-pro": "Gemini 3 Pro (vision)",
    "replicate:meta/llama-3.1-8b-instruct": "Llama 3.1 8B (без vision)",
}
ENHANCE_MODEL_LABEL_TO_SLUG = {
    label: slug for slug, label in ENHANCE_MODEL_SLUG_TO_LABEL.items()
}


def guess_mime_type(name: str) -> str:
    lower = name.lower()
    if lower.endswith(".png"):
        return "image/png"
    if lower.endswith(".webp"):
        return "image/webp"
    return "image/jpeg"


@dataclass
class RefItem:
    name: str
    mime: str = "image/png"
    rel_path: str | None = None
    base64: str | None = None

    def to_dict(self) -> dict[str, Any]:
        out: dict[str, Any] = {"name": self.name, "mime": self.mime}
        if self.rel_path:
            out["rel_path"] = self.rel_path
        if self.base64 and not self.rel_path:
            out["base64"] = self.base64
        return out

    @classmethod
    def from_dict(cls, payload: dict[str, Any] | None) -> RefItem | None:
        if not isinstance(payload, dict):
            return None
        name = str(payload.get("name") or "reference")
        mime = str(payload.get("mime") or guess_mime_type(name))
        rel_path = payload.get("rel_path")
        if isinstance(rel_path, str) and rel_path.strip():
            return cls(name=name, mime=mime, rel_path=rel_path.strip())
        image_b64 = payload.get("base64")
        if isinstance(image_b64, str) and image_b64:
            return cls(name=name, mime=mime, base64=image_b64)
        return None

    def load_base64(self, workspace_root: str) -> str | None:
        if self.base64:
            return self.base64
        if not self.rel_path:
            return None
        path = os.path.normpath(os.path.join(workspace_root, self.rel_path.replace("/", os.sep)))
        ws_norm = os.path.normpath(workspace_root)
        if not path.startswith(ws_norm + os.sep) and path != ws_norm:
            return None
        if not os.path.isfile(path):
            return None
        with open(path, "rb") as f:
            data = base64.b64encode(f.read()).decode("utf-8")
        self.base64 = data
        return data


@dataclass
class GenSettings:
    image_model: str = DEFAULT_IMAGE_MODEL
    size: str = "4K"
    aspect_ratio: str = "match_input_image"
    sequential_image_generation: str = "disabled"
    num_calls: int = 1
    max_images: int = 1
    enhance_model: str = ENHANCE_MODELS[0]
    reasoning: str = "medium"
    max_tokens: str = "4096"

    def to_snapshot(self) -> dict[str, Any]:
        return {
            "image_model": self.image_model,
            "size": self.size,
            "aspect_ratio": self.aspect_ratio,
            "sequential_image_generation": self.sequential_image_generation,
            "num_calls": str(self.num_calls),
            "max_images": str(self.max_images),
            "enhance_model": self.enhance_model,
            "reasoning": self.reasoning,
            "max_tokens": self.max_tokens,
        }

    @classmethod
    def from_snapshot(cls, data: dict[str, Any] | None) -> GenSettings:
        gs = cls()
        if not isinstance(data, dict):
            return gs
        gs.image_model = str(data.get("image_model") or DEFAULT_IMAGE_MODEL)
        gs.size = str(data.get("size") or "4K")
        gs.aspect_ratio = str(data.get("aspect_ratio") or "match_input_image")
        gs.sequential_image_generation = str(data.get("sequential_image_generation") or "disabled")
        try:
            gs.num_calls = max(1, min(15, int(str(data.get("num_calls") or "1"))))
        except ValueError:
            gs.num_calls = 1
        try:
            gs.max_images = max(1, min(15, int(str(data.get("max_images") or "1"))))
        except ValueError:
            gs.max_images = 1
        gs.enhance_model = str(data.get("enhance_model") or ENHANCE_MODELS[0])
        gs.reasoning = str(data.get("reasoning") or "medium")
        gs.max_tokens = str(data.get("max_tokens") or "4096")
        return gs


@dataclass
class BranchState:
    prompt: str = ""
    prompt_enhanced: str = ""
    use_enhanced: bool = False
    refs: list[RefItem] = field(default_factory=list)
    gen: GenSettings = field(default_factory=GenSettings)
    images: list[dict[str, Any]] = field(default_factory=list)
    runs: list[dict[str, Any]] = field(default_factory=list)
