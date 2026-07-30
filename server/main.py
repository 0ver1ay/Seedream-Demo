import os
from typing import Optional, List
from datetime import datetime, timezone
from fastapi import FastAPI
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from server.core import (
    DEFAULT_IMAGE_MODEL,
    IMAGE_MODEL_CONFIGS,
    enhance_text,
    generate_images,
    trace_event,
)


class GenerateRequest(BaseModel):
    prompt: str
    model: Optional[str] = DEFAULT_IMAGE_MODEL
    negative_prompt: Optional[str] = None
    seed: Optional[int] = None
    strength: Optional[float] = None
    num_inference_steps: Optional[int] = None
    guidance_scale: Optional[float] = None
    scheduler: Optional[str] = None
    scope: Optional[str] = "whole-document"
    width: Optional[int] = None
    height: Optional[int] = None
    init_images_base64: Optional[List[str]] = None
    size: Optional[str] = None  # "2K" | "4K"
    aspect_ratio: Optional[str] = None  # "match_input_image" | "1:1" | ...
    sequential_image_generation: Optional[str] = None  # "auto" | "disabled"
    max_images: Optional[int] = None  # up to 15
    token: Optional[str] = None  # optional Replicate token override


class GenerateResponse(BaseModel):
    image_base64: str
    images_base64: Optional[List[str]] = None
class EnhanceRequest(BaseModel):
    text: str
    provider: Optional[str] = "replicate"
    model: Optional[str] = None
    token: Optional[str] = None
    reasoning_effort: Optional[str] = None  # "low" | "medium" | "high"
    max_completion_tokens: Optional[int] = None
    init_images_base64: Optional[List[str]] = None  # optional refs for vision enhance

class EnhanceResponse(BaseModel):
    text: str


app = FastAPI(title="Seedream Proxy")

# Portfolio build: token only from environment (no baked secrets).
_EXPIRES_AT_EPOCH = None
_BAKED_REPLICATE_TOKEN = os.getenv("REPLICATE_API_TOKEN", "").strip()
_TRIAL_EXPIRES_AT = None


@app.middleware("http")
async def trial_guard(request, call_next):
    # Trial restrictions disabled - program can be used at any time
    # if _TRIAL_EXPIRES_AT is not None:
    #     now = datetime.now(timezone.utc)
    #     if now > _TRIAL_EXPIRES_AT:
    #         return JSONResponse(status_code=403, content={"detail": "Trial expired"})
    response = await call_next(request)
    return response

# Allow local plugin calls during development
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/health")
def health():
    return {"status": "ok"}


@app.get("/seedream/models")
def models():
    return {
        "default_model": DEFAULT_IMAGE_MODEL,
        "image_models": IMAGE_MODEL_CONFIGS,
    }


@app.post("/seedream/generate", response_model=GenerateResponse)
def generate(req: GenerateRequest):
    trace_event(
        "http_generate_start",
        model=req.model,
        ref_count=len(req.init_images_base64 or []),
    )
    result = generate_images(req.model_dump(), baked_token=_BAKED_REPLICATE_TOKEN)
    trace_event("http_generate_done", model=req.model)
    return GenerateResponse(**result)


@app.post("/seedream/enhance", response_model=EnhanceResponse)
def enhance(req: EnhanceRequest):
    result = enhance_text(req.model_dump(), baked_token=_BAKED_REPLICATE_TOKEN)
    return EnhanceResponse(**result)


