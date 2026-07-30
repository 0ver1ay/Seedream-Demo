import base64
import hashlib
import io
import json
import os
import sys
import threading
from collections import OrderedDict
from concurrent.futures import Future, ThreadPoolExecutor, as_completed
import time
import traceback
from datetime import datetime
from types import SimpleNamespace
from typing import Any, Callable, Dict, List, Optional

import httpx
import replicate
from replicate.client import Client as ReplicateClient
from replicate.exceptions import ReplicateError
import requests
from fastapi import HTTPException

ContentModerationError = None
try:
    from replicate.helpers.moderation.client import ContentModerationError
except ImportError:
    try:
        from replicate.exceptions import ContentModerationError
    except ImportError:
        pass


IMAGE_MODEL_CONFIGS: Dict[str, Dict[str, Any]] = {
    "bytedance/seedream-5-lite": {
        "label": "Seedream 5 Lite",
        "sizes": ["2K", "3K"],
        "aspect_ratios": ["1:1", "4:3", "3:4", "16:9", "9:16", "3:2", "2:3", "21:9", "match_input_image"],
        "max_reference_images": 14,
        "supports_batch": True,
        "size_field": "size",
        "refs_field": "image_input",
    },
    "bytedance/seedream-4.5": {
        "label": "Seedream 4.5",
        "sizes": ["2K", "4K"],
        "aspect_ratios": ["1:1", "4:3", "3:4", "16:9", "9:16", "3:2", "2:3", "21:9", "match_input_image"],
        "max_reference_images": 10,
        "supports_batch": True,
        "size_field": "size",
        "refs_field": "image_input",
    },
    "google/nano-banana-pro": {
        "label": "Nano Banana Pro",
        "sizes": ["1K", "2K", "4K"],
        "aspect_ratios": ["1:1", "2:3", "3:2", "3:4", "4:3", "4:5", "5:4", "9:16", "16:9", "21:9", "match_input_image"],
        "max_reference_images": 14,
        "supports_batch": False,
        "size_field": "resolution",
        "refs_field": "image_input",
    },
    "google/nano-banana-2": {
        "label": "Nano Banana 2",
        "sizes": ["512", "1K", "2K", "4K"],
        "aspect_ratios": ["1:1", "2:3", "3:2", "3:4", "4:3", "4:5", "5:4", "9:16", "16:9", "21:9", "match_input_image"],
        "max_reference_images": 14,
        "supports_batch": False,
        "size_field": "resolution",
        "refs_field": "image_input",
    },
    "google/nano-banana": {
        "label": "Nano Banana",
        "sizes": ["1K", "2K", "4K"],
        "aspect_ratios": ["1:1", "2:3", "3:2", "3:4", "4:3", "4:5", "5:4", "9:16", "16:9", "21:9", "match_input_image"],
        "max_reference_images": 3,
        "supports_batch": False,
        "size_field": "resolution",
        "refs_field": "image_input",
    },
    "black-forest-labs/flux-2-pro": {
        "label": "FLUX 2 Pro",
        "sizes": ["1 MP", "2 MP", "4 MP"],
        "aspect_ratios": ["1:1", "16:9", "9:16", "4:3", "3:4", "3:2", "2:3", "21:9", "match_input_image"],
        "max_reference_images": 8,
        "supports_batch": False,
        "size_field": "resolution",
        "refs_field": "input_images",
    },
}

DEFAULT_IMAGE_MODEL = "bytedance/seedream-5-lite"

_TERMINAL_STATUSES = frozenset({"succeeded", "failed", "canceled"})

# Replicate recommends HTTP URLs for files >256KB; data URL fallback only for small refs.
_MAX_DATA_URL_FALLBACK_BYTES = 256 * 1024


def _max_data_url_string_chars() -> int:
    raw = os.getenv("SEEDREAM_REF_DATAURL_MAX_CHARS", "").strip()
    try:
        n = int(raw) if raw else 400_000
    except ValueError:
        n = 400_000
    return max(50_000, min(2_000_000, n))


def _prepared_ref_data_url(data: bytes, ctype: str) -> str:
    mime = "image/jpeg"
    if isinstance(ctype, str) and "/" in ctype:
        mime = ctype.split(";")[0].strip().lower() or mime
    payload = base64.b64encode(data).decode("ascii")
    return f"data:{mime};base64,{payload}"
# One HTTP upload per reference (cache_key); parallel generate_images() threads wait on a
# shared Future instead of holding a lock across files.create (which looked like a hang).
_ref_upload_cache: "OrderedDict[str, str]" = OrderedDict()
_ref_upload_cache_lock = threading.Lock()
_inflight_ref_uploads: Dict[str, Future] = {}
_REF_UPLOAD_CACHE_MAX = 48


def _ref_b64_cache_key(b64: str) -> str:
    return hashlib.sha256(b64.encode("utf-8", errors="surrogateescape")).hexdigest()


def _ref_cache_get_unlocked(key: str) -> Optional[str]:
    url = _ref_upload_cache.get(key)
    if url is not None:
        _ref_upload_cache.move_to_end(key)
    return url


def _ref_cache_put_unlocked(key: str, url: str) -> None:
    _ref_upload_cache[key] = url
    _ref_upload_cache.move_to_end(key)
    while len(_ref_upload_cache) > _REF_UPLOAD_CACHE_MAX:
        _ref_upload_cache.popitem(last=False)


def _ref_cache_get(key: str) -> Optional[str]:
    with _ref_upload_cache_lock:
        return _ref_cache_get_unlocked(key)


def _ref_cache_put(key: str, url: str) -> None:
    with _ref_upload_cache_lock:
        _ref_cache_put_unlocked(key, url)


def _ref_upload_inflight_timeout_s() -> float:
    raw = os.getenv("SEEDREAM_REF_UPLOAD_INFLIGHT_TIMEOUT_SECONDS", "").strip()
    try:
        t = float(raw) if raw else 600.0
    except ValueError:
        t = 600.0
    return max(120.0, min(7200.0, t))


def _trace_log_path() -> Optional[str]:
    explicit = os.getenv("SEEDREAM_LOG_FILE", "").strip()
    if explicit:
        return explicit
    if getattr(sys, "frozen", False):
        return os.path.join(os.path.dirname(sys.executable), "log.txt")
    candidate = os.path.normpath(os.path.join(os.path.dirname(__file__), "..", "desktop-app", "log.txt"))
    if os.path.isdir(os.path.dirname(candidate)):
        return candidate
    return None


def trace_event(event: str, **fields: Any) -> None:
    path = _trace_log_path()
    if not path:
        return
    row: Dict[str, Any] = {
        "ts": datetime.now().isoformat(timespec="seconds"),
        "event": event,
        "pid": os.getpid(),
    }
    row.update(fields)
    try:
        with open(path, "a", encoding="utf-8") as f:
            f.write(json.dumps(row, ensure_ascii=False, default=str) + "\n")
            f.flush()
            try:
                os.fsync(f.fileno())
            except (OSError, AttributeError):
                pass
    except Exception as exc:
        try:
            alt = os.path.join(os.path.expanduser("~"), "seedream_trace_fallback.log")
            with open(alt, "a", encoding="utf-8") as f:
                f.write(
                    json.dumps(
                        {**row, "trace_write_error": f"{type(exc).__name__}: {exc}"},
                        ensure_ascii=False,
                        default=str,
                    )
                    + "\n"
                )
        except Exception:
            pass


def _max_prediction_wall_seconds() -> float:
    raw = os.getenv("SEEDREAM_REPLICATE_MAX_WAIT_SECONDS", "").strip()
    try:
        total = float(raw) if raw else 7200.0
    except ValueError:
        total = 7200.0
    return max(300.0, min(86400.0, total))


def get_image_model_config(model: Optional[str]) -> Dict[str, Any]:
    slug = model or DEFAULT_IMAGE_MODEL
    base = IMAGE_MODEL_CONFIGS.get(slug, IMAGE_MODEL_CONFIGS[DEFAULT_IMAGE_MODEL])
    config = dict(base)
    config.setdefault("size_field", "size")
    config.setdefault("refs_field", "image_input")
    config.setdefault("supports_batch", False)
    config.setdefault("max_reference_images", 1)
    config.setdefault("sizes", ["2K"])
    config.setdefault("aspect_ratios", ["1:1", "match_input_image"])
    return config


def build_replicate_image_inputs(
    config: Dict[str, Any],
    *,
    prompt: str,
    size: Optional[str],
    aspect_ratio: Optional[str],
    image_urls: List[str],
    max_images: int,
    sequential_image_generation: Optional[str],
) -> Dict[str, Any]:
    """Map UI payload fields onto the model-specific Replicate input schema."""
    inputs: Dict[str, Any] = {"prompt": prompt}
    size_field = str(config.get("size_field") or "size")
    refs_field = str(config.get("refs_field") or "image_input")
    if size:
        inputs[size_field] = size
    if aspect_ratio:
        inputs["aspect_ratio"] = aspect_ratio
    if config.get("supports_batch"):
        inputs["max_images"] = max(1, int(max_images))
        if sequential_image_generation:
            inputs["sequential_image_generation"] = sequential_image_generation
    if image_urls:
        inputs[refs_field] = list(image_urls)
    return inputs


def is_content_moderation_error(exc: Exception) -> bool:
    if ContentModerationError and isinstance(exc, ContentModerationError):
        return True
    error_type_name = type(exc).__name__
    if "ContentModeration" in error_type_name or "ModerationError" in error_type_name:
        return True
    error_msg = str(exc).lower()
    if (
        "flagged for" in error_msg
        or "content moderation" in error_msg
        or "flagged as sensitive" in error_msg
        or ("sensitive" in error_msg and "flag" in error_msg)
        or "e005" in error_msg
    ):
        return True
    return False


def handle_moderation_error(exc: Exception) -> None:
    error_msg = str(exc)
    error_lower = error_msg.lower()
    if "sexual" in error_lower:
        raise HTTPException(
            status_code=400,
            detail=(
                "Content flagged for moderation (sexual content). "
                "Try more neutral, technical, or abstract wording."
            ),
        )
    if "sensitive" in error_lower or "e005" in error_lower:
        raise HTTPException(
            status_code=400,
            detail=(
                "Content flagged as sensitive (E005). "
                "Try more abstract wording and avoid explicit anatomical descriptions."
            ),
        )
    raise HTTPException(status_code=400, detail=f"Content flagged for moderation: {error_msg}")


def _replicate_api_base_url() -> str:
    base = (os.getenv("REPLICATE_BASE_URL") or "").strip() or "https://api.replicate.com"
    return base.rstrip("/")


def _replicate_ref_requests_fallback_enabled() -> bool:
    v = os.getenv("SEEDREAM_REF_UPLOAD_REQUESTS_FALLBACK", "1").strip().lower()
    return v not in ("0", "false", "no", "off")


def _ref_upload_requests_verify_certs() -> bool:
    """TLS verify for requests-based /v1/files upload. Disable only behind broken MITM proxies (insecure)."""
    if os.getenv("SEEDREAM_INSECURE_SSL", "").strip().lower() in ("1", "true", "yes", "on"):
        return False
    v = os.getenv("SEEDREAM_REF_UPLOAD_VERIFY_SSL", "").strip().lower()
    if v in ("0", "false", "no", "off"):
        return False
    return True


def _replicate_upload_file_via_requests(api_token: str, data: bytes, fname: str, ctype: str) -> Any:
    """POST /v1/files with urllib3/requests (HTTP/1.1). Used when httpx/SDK uploads keep getting RemoteProtocolError."""
    url = f"{_replicate_api_base_url()}/v1/files"
    headers = {
        "Authorization": f"Bearer {api_token}",
        "User-Agent": "seedream-ref-upload/requests",
    }
    raw_to = os.getenv("SEEDREAM_REF_REQUESTS_UPLOAD_TIMEOUT", "").strip()
    try:
        read_s = float(raw_to) if raw_to else 240.0
    except ValueError:
        read_s = 240.0
    read_s = max(60.0, min(900.0, read_s))
    timeout = (30.0, read_s)
    verify = _ref_upload_requests_verify_certs()
    if not verify:
        trace_event(
            "ref_upload_requests_verify_ssl_disabled",
            url_prefix=url[:48],
            hint="SEEDREAM_REF_UPLOAD_VERIFY_SSL=0 or SEEDREAM_INSECURE_SSL=1; TLS verification off for this upload only.",
        )
    resp = requests.post(
        url,
        headers=headers,
        files={"content": (fname, data, ctype)},
        timeout=timeout,
        verify=verify,
    )
    if resp.status_code >= 400:
        raise RuntimeError(f"Replicate POST /v1/files HTTP {resp.status_code}: {resp.text[:800]}")
    body = resp.json()
    if not isinstance(body, dict):
        raise RuntimeError("Replicate file response is not a JSON object")
    urls = body.get("urls")
    if not isinstance(urls, dict) or not isinstance(urls.get("get"), str):
        raise RuntimeError(f"Replicate file response missing urls.get: {str(body)[:400]}")
    return SimpleNamespace(urls=urls)


def _replicate_file_get_url(uploaded: Any) -> Optional[str]:
    if isinstance(uploaded, str) and uploaded.startswith("http"):
        return uploaded
    urls = getattr(uploaded, "urls", None)
    if isinstance(urls, dict):
        for key in ("get", "stream"):
            u = urls.get(key)
            if isinstance(u, str) and u.startswith("http"):
                return u
    u = getattr(uploaded, "url", None)
    if isinstance(u, str) and u.startswith("http"):
        return u
    return None


def _ref_soft_max_bytes() -> int:
    raw = os.getenv("SEEDREAM_REF_SOFT_BYTES", "").strip()
    try:
        return int(raw) if raw else 512 * 1024
    except ValueError:
        return 512 * 1024


def _ref_target_max_bytes() -> int:
    raw = os.getenv("SEEDREAM_REF_TARGET_MAX_BYTES", "").strip()
    try:
        # Default ~200 KB JPEG: smaller multipart bodies hit fewer RemoteProtocolError drops.
        return int(raw) if raw else 200_000
    except ValueError:
        return 200_000


def _ref_max_edge() -> int:
    raw = os.getenv("SEEDREAM_REF_MAX_EDGE", "").strip()
    try:
        return int(raw) if raw else 2048
    except ValueError:
        return 2048


def _prepare_ref_image_for_upload(data: bytes) -> tuple[bytes, str, str]:
    """
    Shrink heavy references before Replicate files.create (upload is fragile on multi-MB bodies).
    Returns (bytes, filename, content_type).
    """
    soft = _ref_soft_max_bytes()
    max_edge = _ref_max_edge()
    target_max = _ref_target_max_bytes()
    orig_len = len(data)

    try:
        from PIL import Image
    except ImportError:
        trace_event("ref_prepare_skip_no_pillow", orig_bytes=orig_len)
        return data, "seedream_ref.png", "image/png"

    try:
        img = Image.open(io.BytesIO(data))
        img.load()
    except Exception:
        trace_event("ref_prepare_not_image", orig_bytes=orig_len)
        return data, "seedream_ref.png", "image/png"

    w, h = img.size
    if orig_len <= soft and max(w, h) <= max_edge:
        trace_event("ref_prepare_skip_small", orig_bytes=orig_len, w=w, h=h)
        if (getattr(img, "format", "") or "").upper() in ("JPEG", "JPG") and img.mode == "RGB":
            return data, "seedream_ref.jpg", "image/jpeg"
        buf = io.BytesIO()
        icc = img.info.get("icc_profile")
        save_kw: Dict[str, Any] = {"format": "PNG", "optimize": True}
        if icc:
            save_kw["icc_profile"] = icc
        try:
            img.save(buf, **save_kw)
        except TypeError:
            save_kw.pop("icc_profile", None)
            buf = io.BytesIO()
            img.save(buf, format="PNG", optimize=True)
        out = buf.getvalue()
        return out, "seedream_ref.png", "image/png"

    if img.mode == "RGBA":
        bg = Image.new("RGB", img.size, (255, 255, 255))
        bg.paste(img, mask=img.split()[3])
        img = bg
    elif img.mode != "RGB":
        img = img.convert("RGB")

    scale = min(1.0, float(max_edge) / float(max(w, h)))
    if scale < 1.0:
        nw, nh = max(1, int(w * scale)), max(1, int(h * scale))
        img = img.resize((nw, nh), Image.LANCZOS)

    out: bytes = b""
    for q in (88, 82, 76, 70, 64, 58, 52):
        buf = io.BytesIO()
        img.save(buf, format="JPEG", quality=q, optimize=True)
        out = buf.getvalue()
        if len(out) <= target_max:
            break

    if len(out) > target_max and max(img.size) > 1024:
        w2, h2 = img.size
        img = img.resize((max(1, int(w2 * 0.65)), max(1, int(h2 * 0.65))), Image.LANCZOS)
        buf = io.BytesIO()
        img.save(buf, format="JPEG", quality=62, optimize=True)
        out = buf.getvalue()

    trace_event(
        "ref_prepare_compressed",
        orig_bytes=orig_len,
        out_bytes=len(out),
        orig_wh=(w, h),
        final_wh=(img.size[0], img.size[1]),
    )
    return out, "seedream_ref.jpg", "image/jpeg"


def _ref_upload_sdk_attempts() -> int:
    raw = os.getenv("SEEDREAM_REF_UPLOAD_SDK_ATTEMPTS", "").strip()
    try:
        # Default 2: RemoteProtocolError on httpx rarely self-heals with many retries; requests fallback is faster.
        n = int(raw) if raw else 2
    except ValueError:
        n = 2
    return max(1, min(16, n))


def _ref_upload_requests_attempts() -> int:
    raw = os.getenv("SEEDREAM_REF_UPLOAD_REQUESTS_ATTEMPTS", "").strip()
    try:
        n = int(raw) if raw else 5
    except ValueError:
        n = 5
    return max(1, min(12, n))


def _ref_upload_parallel_workers() -> int:
    raw = os.getenv("SEEDREAM_REF_UPLOAD_WORKERS", "").strip()
    try:
        w = int(raw) if raw else 6
    except ValueError:
        w = 6
    return max(1, min(12, w))


def _upload_single_ref_with_client(client: ReplicateClient, api_token: str, idx: int, b64: str) -> str:
    t0 = time.perf_counter()
    cache_key = _ref_b64_cache_key(b64)
    cached = _ref_cache_get(cache_key)
    if cached:
        trace_event("ref_upload_cache_hit", index=idx, bytes=0, elapsed_s=round(time.perf_counter() - t0, 3))
        return cached

    raw = base64.b64decode(b64)
    data, fname, ctype = _prepare_ref_image_for_upload(raw)
    trace_event("ref_upload_start", index=idx, bytes=len(data), prepared_from=len(raw))

    files_api = client.files
    if not hasattr(files_api, "create") and not hasattr(files_api, "upload"):
        raise HTTPException(status_code=500, detail="Replicate client.files has neither create nor upload")

    fut: Optional[Future] = None
    is_leader = False
    with _ref_upload_cache_lock:
        cached_in = _ref_cache_get_unlocked(cache_key)
        if cached_in:
            trace_event(
                "ref_upload_cache_hit_after_prepare",
                index=idx,
                elapsed_s=round(time.perf_counter() - t0, 3),
            )
            return cached_in
        if cache_key in _inflight_ref_uploads:
            fut = _inflight_ref_uploads[cache_key]
        else:
            fut = Future()
            _inflight_ref_uploads[cache_key] = fut
            is_leader = True

    if not is_leader:
        assert fut is not None
        try:
            trace_event("ref_upload_inflight_wait", index=idx, timeout_s=_ref_upload_inflight_timeout_s())
            url = fut.result(timeout=_ref_upload_inflight_timeout_s())
            trace_event(
                "ref_upload_inflight_done",
                index=idx,
                elapsed_s=round(time.perf_counter() - t0, 3),
            )
            return url
        except TimeoutError:
            trace_event(
                "ref_upload_inflight_timeout",
                index=idx,
                elapsed_s=round(time.perf_counter() - t0, 3),
            )
            raise HTTPException(
                status_code=502,
                detail=(
                    "Timed out waiting for another thread to finish the same reference upload. "
                    "Try SEEDREAM_REF_UPLOAD_INFLIGHT_TIMEOUT_SECONDS or disable parallel calls."
                ),
            )

    assert fut is not None

    def _release_inflight(exc: BaseException | None) -> None:
        with _ref_upload_cache_lock:
            _inflight_ref_uploads.pop(cache_key, None)
            if exc is not None and not fut.done():
                fut.set_exception(exc)

    try:

        def _create_file():
            if hasattr(files_api, "create"):
                buf = io.BytesIO(data)
                return files_api.create(buf, filename=fname, content_type=ctype)
            return files_api.upload(data, filename=fname)  # type: ignore[attr-defined]

        trace_event("ref_upload_leader_create", index=idx, bytes=len(data))
        hb_stop = threading.Event()

        def _upload_heartbeat() -> None:
            interval = 25.0
            raw = os.getenv("SEEDREAM_REF_UPLOAD_HEARTBEAT_SECONDS", "").strip()
            try:
                if raw:
                    interval = float(raw)
            except ValueError:
                pass
            interval = max(10.0, min(120.0, interval))
            while not hb_stop.wait(interval):
                trace_event(
                    "ref_upload_leader_heartbeat",
                    index=idx,
                    bytes=len(data),
                    waited_s=round(time.perf_counter() - t0, 1),
                )

        hb_thread = threading.Thread(target=_upload_heartbeat, name="ref_upload_hb", daemon=True)
        hb_thread.start()
        try:
            try:
                uploaded = _retry_transient(
                    _create_file,
                    attempts=_ref_upload_sdk_attempts(),
                    base_delay=0.75,
                    trace_transient_extra={"purpose": "ref_upload", "index": idx, "bytes": len(data)},
                )
            except Exception as sdk_exc:
                if _replicate_ref_requests_fallback_enabled() and _is_transient_network_error(sdk_exc):
                    trace_event(
                        "ref_upload_sdk_retries_exhausted",
                        index=idx,
                        bytes=len(data),
                        error=f"{type(sdk_exc).__name__}: {sdk_exc}",
                        hint=(
                            "If requests fallback then shows SSLError/EOF: try another network/VPN, or only if you "
                            "trust the path set SEEDREAM_REF_UPLOAD_VERIFY_SSL=0 (or SEEDREAM_INSECURE_SSL=1) — "
                            "disables TLS verify for ref upload only."
                        ),
                    )
                    t_rq = time.perf_counter()

                    def _create_via_requests():
                        return _replicate_upload_file_via_requests(api_token, data, fname, ctype)

                    uploaded = _retry_transient(
                        _create_via_requests,
                        attempts=_ref_upload_requests_attempts(),
                        base_delay=1.0,
                        trace_transient_extra={
                            "purpose": "ref_upload_requests",
                            "index": idx,
                            "bytes": len(data),
                        },
                    )
                    trace_event(
                        "ref_upload_requests_ok",
                        index=idx,
                        elapsed_s=round(time.perf_counter() - t_rq, 3),
                    )
                else:
                    raise
        finally:
            hb_stop.set()
            hb_thread.join(timeout=3.0)
        final_url = _replicate_file_get_url(uploaded)
        if not final_url:
            raise RuntimeError("Upload returned no HTTP URL")
        trace_event(
            "ref_upload_done",
            index=idx,
            elapsed_s=round(time.perf_counter() - t0, 3),
            url_kind="http" if str(final_url).startswith("http") else "other",
        )
        with _ref_upload_cache_lock:
            _ref_cache_put_unlocked(cache_key, final_url)
            if not fut.done():
                fut.set_result(final_url)
            _inflight_ref_uploads.pop(cache_key, None)
        return final_url
    except Exception as exc:
        trace_event(
            "ref_upload_failed",
            index=idx,
            error=f"{type(exc).__name__}: {exc}",
            bytes=len(data),
            elapsed_s=round(time.perf_counter() - t0, 3),
        )
        if len(data) > _MAX_DATA_URL_FALLBACK_BYTES:
            _release_inflight(exc)
            raise HTTPException(
                status_code=502,
                detail=(
                    f"Replicate file upload failed for reference (~{len(data) // 1024} KB): {type(exc).__name__}: {exc}. "
                    "Do not use data-URL fallback for large files. Try a smaller reference, disable parallel "
                    "generation calls, check VPN/firewall, or retry."
                ),
            ) from exc
        data_url = _prepared_ref_data_url(data, ctype)
        if len(data_url) > _max_data_url_string_chars():
            _release_inflight(exc)
            raise HTTPException(
                status_code=502,
                detail=(
                    f"Replicate file upload failed and the prepared reference is too large for an in-JSON data URL "
                    f"({len(data_url)} chars, max {_max_data_url_string_chars()}): {type(exc).__name__}: {exc}. "
                    "Retry, compress the image further, or raise SEEDREAM_REF_DATAURL_MAX_CHARS if appropriate."
                ),
            ) from exc
        trace_event(
            "ref_upload_small_data_url_fallback",
            index=idx,
            bytes=len(data),
            data_url_chars=len(data_url),
        )
        with _ref_upload_cache_lock:
            _ref_cache_put_unlocked(cache_key, data_url)
            if not fut.done():
                fut.set_result(data_url)
            _inflight_ref_uploads.pop(cache_key, None)
        return data_url


def _upload_reference_images(
    rep_client: ReplicateClient,
    api_token: str,
    init_images_base64: Optional[List[str]],
    max_count: int,
) -> List[str]:
    image_urls: List[str] = []
    n = len(init_images_base64) if init_images_base64 else 0
    trace_event("upload_refs_enter", raw_count=n, max_count=max_count)
    if not init_images_base64:
        trace_event("upload_refs_none", reason="no init_images_base64")
        return image_urls

    slice_b64 = init_images_base64[:max_count]
    n_slice = len(slice_b64)
    workers = _ref_upload_parallel_workers()
    workers = min(workers, n_slice)

    if n_slice <= 1 or workers <= 1:
        for idx, b64 in enumerate(slice_b64):
            u = _upload_single_ref_with_client(rep_client, api_token, idx, b64)
            if isinstance(u, str) and (u.startswith("http") or u.startswith("data:")):
                image_urls.append(u)
        return image_urls

    trace_event("upload_refs_parallel", refs=n_slice, workers=workers)

    def _job(args: tuple[int, str]) -> tuple[int, str]:
        idx, b64 = args
        c = _make_replicate_client(api_token)
        return idx, _upload_single_ref_with_client(c, api_token, idx, b64)

    ordered: List[Optional[str]] = [None] * n_slice
    with ThreadPoolExecutor(max_workers=workers) as ex:
        future_map = {ex.submit(_job, (i, b)): i for i, b in enumerate(slice_b64)}
        for fut in as_completed(future_map):
            idx, url = fut.result()
            ordered[idx] = url
    for u in ordered:
        if isinstance(u, str) and (u.startswith("http") or u.startswith("data:")):
            image_urls.append(u)
    return image_urls


def _normalize_aspect_ratio(aspect_ratio: Optional[str], has_inputs: bool) -> Optional[str]:
    if not aspect_ratio:
        return None
    if aspect_ratio == "match_input_image" and not has_inputs:
        return "1:1"
    return aspect_ratio


def _replicate_http_timeout() -> httpx.Timeout:
    raw = os.getenv("SEEDREAM_REPLICATE_HTTP_TIMEOUT_SECONDS", "").strip()
    try:
        total = float(raw) if raw else 900.0
    except ValueError:
        total = 900.0
    total = max(60.0, min(3600.0, total))
    return httpx.Timeout(total, read=total, write=min(120.0, total), connect=30.0, pool=30.0)


def _make_replicate_client(api_token: str) -> ReplicateClient:
    trace_event(
        "replicate_client_instantiate",
        token_len=len(api_token) if api_token else 0,
        timeout=str(_replicate_http_timeout()),
    )
    client = ReplicateClient(api_token=api_token, timeout=_replicate_http_timeout())
    trace_event("replicate_client_ready", poll_interval=getattr(client, "poll_interval", None))
    return client


def _is_transient_network_error(exc: Exception) -> bool:
    if isinstance(exc, (httpx.ReadTimeout, httpx.ConnectTimeout, httpx.RemoteProtocolError)):
        return True
    if isinstance(exc, (httpx.TransportError, ConnectionError, OSError)):
        return True
    if isinstance(
        exc,
        (
            requests.exceptions.Timeout,
            requests.exceptions.ConnectionError,
            requests.exceptions.ChunkedEncodingError,
        ),
    ):
        return True
    if isinstance(exc, requests.exceptions.SSLError):
        m = str(exc).lower()
        if "certificate verify failed" in m or "hostname mismatch" in m:
            return False
        return True
    if isinstance(exc, requests.exceptions.HTTPError):
        resp = getattr(exc, "response", None)
        if resp is not None and resp.status_code in (429, 502, 503, 504):
            return True
    msg = str(exc).lower()
    if "timed out" in msg or "disconnected" in msg or "connection reset" in msg:
        return True
    if "ssleof" in msg or "ssl eof" in msg:
        return True
    if "eof occurred in violation of protocol" in msg:
        return True
    return False


def _retry_transient(
    fn,
    *,
    attempts: int = 10,
    base_delay: float = 0.5,
    trace_transient_extra: Optional[Dict[str, Any]] = None,
):
    last_exc: Optional[Exception] = None
    for attempt in range(attempts):
        try:
            return fn()
        except Exception as exc:
            last_exc = exc
            if attempt == attempts - 1 or not _is_transient_network_error(exc):
                raise
            delay = min(8.0, base_delay * (2**attempt)) + (0.05 * attempt)
            if trace_transient_extra is not None:
                trace_event(
                    "retry_transient",
                    **trace_transient_extra,
                    attempt=attempt + 1,
                    attempts=attempts,
                    error=f"{type(exc).__name__}: {exc}",
                    next_sleep_s=round(delay, 2),
                )
            time.sleep(delay)
    raise last_exc  # pragma: no cover


def _prediction_reload(prediction: Any) -> None:
    def _do():
        prediction.reload()

    _retry_transient(_do)


def _prediction_wait(prediction: Any, *, cancel_event: Optional[threading.Event] = None) -> None:
    trace_event(
        "replicate_prediction_wait_enter",
        prediction_id=getattr(prediction, "id", None),
        initial_status=getattr(prediction, "status", None),
    )
    consecutive_reload_failures = 0
    t_wall = time.monotonic()
    max_wall = _max_prediction_wall_seconds()
    last_status: Optional[str] = None
    last_heartbeat = time.monotonic()
    poll = float(getattr(getattr(prediction, "_client", None), "poll_interval", None) or 1.0)
    poll = max(0.25, poll)
    pred_id = getattr(prediction, "id", None)

    while prediction.status not in _TERMINAL_STATUSES:
        if cancel_event is not None and cancel_event.is_set():
            pred_id = getattr(prediction, "id", None)
            if pred_id:
                try:
                    prediction.cancel()
                except Exception:
                    pass
            raise RuntimeError("Generation canceled")
        if time.monotonic() - t_wall > max_wall:
            trace_event(
                "replicate_prediction_timeout",
                prediction_id=pred_id,
                last_status=getattr(prediction, "status", None),
                waited_s=round(time.monotonic() - t_wall, 1),
                max_wait_s=max_wall,
            )
            raise TimeoutError(
                f"Replicate prediction exceeded max wait ({int(max_wall)}s); "
                f"last_status={getattr(prediction, 'status', None)!r}; id={pred_id!r}"
            )

        time.sleep(poll)
        try:
            _prediction_reload(prediction)
            consecutive_reload_failures = 0
        except Exception as exc:
            if not _is_transient_network_error(exc):
                trace_event(
                    "replicate_reload_fatal",
                    prediction_id=pred_id,
                    error=f"{type(exc).__name__}: {exc}",
                )
                raise
            consecutive_reload_failures += 1
            trace_event(
                "replicate_reload_transient",
                prediction_id=pred_id,
                attempt=consecutive_reload_failures,
                error=f"{type(exc).__name__}: {exc}",
            )
            if consecutive_reload_failures >= 40:
                raise
            backoff = min(5.0, 0.25 * (2 ** min(10, consecutive_reload_failures - 1)))
            time.sleep(backoff)

        st = getattr(prediction, "status", None)
        if st != last_status:
            trace_event(
                "replicate_prediction_status",
                prediction_id=pred_id,
                status=st,
                elapsed_s=round(time.monotonic() - t_wall, 1),
            )
            last_status = st

        if time.monotonic() - last_heartbeat >= 30.0:
            trace_event(
                "replicate_prediction_heartbeat",
                prediction_id=pred_id,
                status=st,
                waited_s=round(time.monotonic() - t_wall, 1),
            )
            last_heartbeat = time.monotonic()

        if st in _TERMINAL_STATUSES:
            break


def _inputs_size_hint(inputs: Dict[str, Any]) -> Dict[str, Any]:
    hint: Dict[str, Any] = {}
    p = inputs.get("prompt")
    if isinstance(p, str):
        hint["prompt_chars"] = len(p)
    ij = inputs.get("image_input")
    if isinstance(ij, list):
        hint["image_input_count"] = len(ij)
        hint["image_input_url_lens"] = [len(str(x)) for x in ij[:8]]
    elif ij is not None:
        hint["image_input_type"] = type(ij).__name__
    return hint


def _prediction_urls_for_log(prediction: Any) -> Dict[str, Any]:
    u = getattr(prediction, "urls", None)
    out: Dict[str, Any] = {}
    if isinstance(u, dict):
        if u.get("web"):
            out["urls_web"] = u["web"]
        if u.get("get"):
            out["urls_get_prefix"] = str(u["get"])[:160]
    return out


def _run_replicate_model(
    client: ReplicateClient,
    model: str,
    inputs: Dict[str, Any],
    *,
    progress_callback: Optional[Callable[..., None]] = None,
    cancel_event: Optional[threading.Event] = None,
) -> Any:
    trace_event(
        "replicate_run_model_enter",
        model=model,
        input_keys=sorted(inputs.keys()),
        has_image_input=bool(inputs.get("image_input")),
    )

    def _create():
        trace_event(
            "replicate_predictions_create_call",
            model=model,
            **_inputs_size_hint(inputs),
        )
        t_inner = time.perf_counter()
        try:
            pred = client.predictions.create(model=model, input=inputs)
        except Exception as exc:
            err: Dict[str, Any] = {
                "model": model,
                "error_type": type(exc).__name__,
                "error_str": str(exc)[:4000],
            }
            if isinstance(exc, ReplicateError):
                err.update(
                    {
                        "http_status": exc.status,
                        "title": exc.title,
                        "detail": exc.detail,
                        "instance": exc.instance,
                    }
                )
            trace_event("replicate_predictions_create_failed", **err)
            raise
        url_meta = _prediction_urls_for_log(pred)
        trace_event(
            "replicate_predictions_create_ok",
            model=model,
            prediction_id=getattr(pred, "id", None),
            status=getattr(pred, "status", None),
            version=getattr(pred, "version", None),
            source=getattr(pred, "source", None),
            elapsed_s=round(time.perf_counter() - t_inner, 3),
            **url_meta,
        )
        pid = getattr(pred, "id", None)
        web = url_meta.get("urls_web") or (f"https://replicate.com/p/{pid}" if pid else None)
        trace_event(
            "replicate_dashboard_hint",
            prediction_id=pid,
            urls_web=web,
            hint=(
                "Если в веб-админке пусто: зайдите под тем же аккаунтом, что и API-токен; "
                "предикты из приложения — source=api (не включайте фильтр только playground/web). "
                "Прямая ссылка — urls_web. Список: GET /v1/predictions с этим Bearer."
            ),
        )
        return pred

    if progress_callback:
        progress_callback("predict_create", model=model)
    t0 = time.perf_counter()
    trace_event("replicate_create_start", model=model, input_keys=sorted(inputs.keys()))
    prediction = _retry_transient(_create)
    trace_event(
        "replicate_create_done",
        prediction_id=getattr(prediction, "id", None),
        initial_status=getattr(prediction, "status", None),
        elapsed_s=round(time.perf_counter() - t0, 3),
        **_prediction_urls_for_log(prediction),
    )
    try:
        if progress_callback:
            progress_callback("predict_wait", prediction_id=getattr(prediction, "id", None))
        _prediction_wait(prediction, cancel_event=cancel_event)
    except Exception as exc:
        trace_event(
            "replicate_wait_failed",
            prediction_id=getattr(prediction, "id", None),
            error=f"{type(exc).__name__}: {exc}",
        )
        raise
    trace_event(
        "replicate_wait_done",
        prediction_id=getattr(prediction, "id", None),
        status=getattr(prediction, "status", None),
        waited_s=round(time.perf_counter() - t0, 3),
    )
    if progress_callback:
        progress_callback("predict_done", status=getattr(prediction, "status", None))
    if prediction.status == "failed":
        raise RuntimeError(getattr(prediction, "error", None) or "Prediction failed")
    if prediction.status == "canceled":
        raise RuntimeError("Prediction canceled")
    return prediction.output


def _normalize_output_items(output: Any) -> List[Any]:
    if output is None:
        return []
    if isinstance(output, (str, bytes)):
        return [output]
    if isinstance(output, list):
        return output
    if isinstance(output, tuple):
        return list(output)
    if hasattr(output, "read") or getattr(output, "url", None):
        return [output]
    try:
        return list(output)
    except TypeError:
        return [output]


def _read_output_bytes(item: Any, *, item_index: int = 0) -> Optional[bytes]:
    if item is None:
        return None
    if isinstance(item, bytes):
        trace_event("output_item_bytes", item_index=item_index, bytes=len(item))
        return item
    if isinstance(item, str):
        if item.startswith("data:") and "," in item:
            try:
                out = base64.b64decode(item.split(",", 1)[1])
                trace_event("output_item_data_url", item_index=item_index, bytes=len(out))
                return out
            except Exception:
                return None
        t0 = time.perf_counter()
        trace_event("output_download_start", item_index=item_index, url_prefix=item[:120])
        try:
            response = requests.get(item, timeout=120)
            response.raise_for_status()
            trace_event(
                "output_download_done",
                item_index=item_index,
                bytes=len(response.content),
                elapsed_s=round(time.perf_counter() - t0, 3),
            )
            return response.content
        except Exception as exc:
            trace_event(
                "output_download_error",
                item_index=item_index,
                error=f"{type(exc).__name__}: {exc}",
                traceback=traceback.format_exc(),
            )
            raise

    url = getattr(item, "url", None)
    if isinstance(url, str) and url:
        t0 = time.perf_counter()
        trace_event("output_download_start", item_index=item_index, url_prefix=url[:120])
        try:
            response = requests.get(url, timeout=120)
            response.raise_for_status()
            trace_event(
                "output_download_done",
                item_index=item_index,
                bytes=len(response.content),
                elapsed_s=round(time.perf_counter() - t0, 3),
            )
            return response.content
        except Exception as exc:
            trace_event(
                "output_download_error",
                item_index=item_index,
                error=f"{type(exc).__name__}: {exc}",
                traceback=traceback.format_exc(),
            )
            raise

    reader = getattr(item, "read", None)
    if callable(reader):
        trace_event("output_item_reader", item_index=item_index)
        data = reader()
        if isinstance(data, bytes):
            trace_event("output_reader_bytes", item_index=item_index, bytes=len(data))
            return data
        if isinstance(data, str):
            raw = data.encode("utf-8")
            trace_event("output_reader_str", item_index=item_index, bytes=len(raw))
            return raw

    try:
        chunks = [chunk for chunk in item if isinstance(chunk, bytes)]
    except TypeError:
        chunks = []
    if chunks:
        joined = b"".join(chunks)
        trace_event("output_item_chunks", item_index=item_index, bytes=len(joined))
        return joined
    trace_event("output_item_unrecognized", item_index=item_index, type=type(item).__name__)
    return None


def generate_images(
    payload: Dict[str, Any],
    baked_token: str = "",
    *,
    progress_callback: Optional[Callable[..., None]] = None,
    cancel_event: Optional[threading.Event] = None,
) -> Dict[str, Any]:
    trace_event(
        "generate_images_entry",
        payload_keys=sorted((payload or {}).keys()),
        log_file=_trace_log_path(),
        frozen=getattr(sys, "frozen", False),
        executable=sys.executable if getattr(sys, "frozen", False) else None,
    )
    t_gen = time.perf_counter()
    model = payload.get("model") or DEFAULT_IMAGE_MODEL
    config = get_image_model_config(model)
    api_token = payload.get("token") or os.getenv("REPLICATE_API_TOKEN") or baked_token
    tok_hint = None
    if api_token and isinstance(api_token, str) and len(api_token) > 8:
        tok_hint = f"{api_token[:8]}…{api_token[-4:]}"
    trace_event(
        "generate_images_token_resolved",
        has_token=bool(api_token),
        token_source="payload" if payload.get("token") else ("env" if os.getenv("REPLICATE_API_TOKEN") else "baked"),
        api_token_hint=tok_hint,
        model=model,
    )
    if not api_token:
        trace_event("generate_images_abort", reason="no_api_token")
        raise HTTPException(status_code=500, detail="REPLICATE_API_TOKEN not set")
    os.environ["REPLICATE_API_TOKEN"] = api_token
    trace_event("generate_images_before_client", model=model)
    rep_client = _make_replicate_client(api_token)

    prompt = payload.get("prompt") or ""
    refs_in = payload.get("init_images_base64") or []
    trace_event(
        "generate_images_start",
        model=model,
        frozen=getattr(sys, "frozen", False),
        prompt_len=len(prompt) if isinstance(prompt, str) else 0,
        ref_count=len(refs_in) if isinstance(refs_in, list) else 0,
        max_wait_s=_max_prediction_wall_seconds(),
        http_timeout=str(_replicate_http_timeout()),
    )

    if progress_callback:
        progress_callback("upload_refs", count=len(refs_in) if isinstance(refs_in, list) else 0)
    if cancel_event is not None and cancel_event.is_set():
        raise RuntimeError("Generation canceled")
    image_urls = _upload_reference_images(
        rep_client,
        api_token,
        payload.get("init_images_base64"),
        config["max_reference_images"],
    )

    trace_event("generate_images_refs_ready", uploaded=len(image_urls))
    if progress_callback:
        progress_callback("upload_done", uploaded=len(image_urls))

    aspect_ratio = _normalize_aspect_ratio(payload.get("aspect_ratio"), bool(image_urls))
    requested_max = int(payload.get("max_images") or 1)
    if not config["supports_batch"]:
        requested_max = 1

    inputs = build_replicate_image_inputs(
        config,
        prompt=payload["prompt"],
        size=payload.get("size"),
        aspect_ratio=aspect_ratio,
        image_urls=image_urls,
        max_images=requested_max,
        sequential_image_generation=payload.get("sequential_image_generation"),
    )

    try:
        output = _run_replicate_model(
            rep_client,
            model,
            inputs,
            progress_callback=progress_callback,
            cancel_event=cancel_event,
        )
    except Exception as exc:
        trace_event(
            "generate_images_replicate_error",
            error=f"{type(exc).__name__}: {exc}",
            traceback=traceback.format_exc(),
        )
        if is_content_moderation_error(exc):
            handle_moderation_error(exc)
        raise HTTPException(
            status_code=502,
            detail=f"Replicate error: {type(exc).__name__}: {exc}",
        )

    items = _normalize_output_items(output)
    trace_event("generate_images_output_received", items=len(items), types=[type(x).__name__ for x in items[:5]])

    if progress_callback:
        progress_callback("download", items=len(items))
    images_b64: List[str] = []
    for idx, item in enumerate(items):
        if cancel_event is not None and cancel_event.is_set():
            raise RuntimeError("Generation canceled")
        try:
            content = _read_output_bytes(item, item_index=idx)
            if content:
                images_b64.append(base64.b64encode(content).decode("utf-8"))
        except Exception as exc:
            trace_event(
                "generate_images_item_skip",
                item_index=idx,
                error=f"{type(exc).__name__}: {exc}",
            )
            continue

    if not images_b64:
        trace_event("generate_images_no_bytes", items=len(items))
        raise HTTPException(status_code=502, detail="Failed to download generated image(s)")
    trace_event(
        "generate_images_done",
        images=len(images_b64),
        elapsed_s=round(time.perf_counter() - t_gen, 3),
    )
    return {"image_base64": images_b64[0], "images_base64": images_b64}


def _enhance_image_field(model: str) -> Optional[str]:
    """Which Replicate input key accepts images for this enhance model, if any."""
    m = (model or "").lower()
    if m.startswith("openai/") or "gpt-5" in m or "gpt-4o" in m or "gpt-4.1" in m:
        return "image_input"
    if m.startswith("google/") or "gemini" in m:
        return "images"
    return None


def _enhance_instruction(text: str, *, has_images: bool) -> str:
    if has_images:
        return (
            "Improve the prompt for a visual neural network using the attached reference image(s). "
            "Preserve identity, composition cues, lighting and style visible in the references when relevant. "
            "As the response, provide the improved prompt as a single paragraph based on this request: "
            f'"{text}"'
        )
    return (
        "Improve the prompt for a visual neural network. "
        f'As the response, provide the improved prompt as a single paragraph: "{text}"'
    )


def _b64_to_data_url(b64: str) -> str:
    raw = base64.b64decode(b64)
    data, _fname, ctype = _prepare_ref_image_for_upload(raw)
    encoded = base64.b64encode(data).decode("ascii")
    return f"data:{ctype};base64,{encoded}"


def enhance_text(payload: Dict[str, Any], baked_token: str = "") -> Dict[str, str]:
    provider = (payload.get("provider") or "replicate").lower()
    model = payload.get("model") or "meta/llama-3.1-8b-instruct"
    text = payload["text"]
    refs_b64 = [b for b in (payload.get("init_images_base64") or []) if isinstance(b, str) and b.strip()]
    # Keep enhance latency reasonable
    refs_b64 = refs_b64[:4]
    has_images = bool(refs_b64)
    improved_prompt_instruction = _enhance_instruction(text, has_images=has_images)

    if provider == "replicate":
        token = payload.get("token") or os.getenv("REPLICATE_API_TOKEN") or baked_token
        if not token:
            raise HTTPException(status_code=500, detail="REPLICATE_API_TOKEN not set and no token provided")
        os.environ["REPLICATE_API_TOKEN"] = token
        rep_input: Dict[str, Any] = {"prompt": improved_prompt_instruction}
        if payload.get("reasoning_effort"):
            rep_input["reasoning_effort"] = payload["reasoning_effort"]
        if payload.get("max_completion_tokens") is not None:
            rep_input["max_completion_tokens"] = payload["max_completion_tokens"]

        image_field = _enhance_image_field(model)
        if has_images and image_field:
            try:
                rep_client = _make_replicate_client(token)
                image_urls = _upload_reference_images(rep_client, token, refs_b64, len(refs_b64))
            except HTTPException:
                raise
            except Exception as exc:
                raise HTTPException(status_code=502, detail=f"Failed to upload enhance references: {exc}")
            if image_urls:
                rep_input[image_field] = image_urls
                trace_event("enhance_refs_attached", model=model, field=image_field, count=len(image_urls))
            else:
                trace_event("enhance_refs_upload_empty", model=model)
        elif has_images:
            trace_event("enhance_refs_skipped_no_vision", model=model, count=len(refs_b64))

        try:
            rep_client = _make_replicate_client(token)
            out = rep_client.run(model, input=rep_input)
        except Exception as exc:
            if is_content_moderation_error(exc):
                handle_moderation_error(exc)
            raise HTTPException(status_code=502, detail=f"Replicate enhance error: {exc}")
        if isinstance(out, list):
            return {"text": "".join(str(item) for item in out).strip() or text}
        return {"text": str(out).strip() or text}

    if provider == "openai":
        token = payload.get("token") or os.getenv("OPENAI_API_KEY")
        if not token:
            raise HTTPException(status_code=500, detail="OPENAI_API_KEY not set")
        content: List[Any] = [{"type": "text", "text": improved_prompt_instruction}]
        for b64 in refs_b64:
            try:
                content.append({"type": "image_url", "image_url": {"url": _b64_to_data_url(b64)}})
            except Exception:
                continue
        try:
            with httpx.Client(timeout=120) as client:
                response = client.post(
                    "https://api.openai.com/v1/chat/completions",
                    headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
                    json={
                        "model": model,
                        "messages": [{"role": "user", "content": content}],
                        "temperature": 0.3,
                    },
                )
                response.raise_for_status()
                data = response.json()
                out_text = data["choices"][0]["message"]["content"].strip()
                return {"text": out_text or text}
        except Exception as exc:
            raise HTTPException(status_code=502, detail=f"OpenAI enhance error: {exc}")

    if provider == "google":
        token = payload.get("token") or os.getenv("GOOGLE_API_KEY")
        if not token:
            raise HTTPException(status_code=500, detail="GOOGLE_API_KEY not set and no token provided")
        parts: List[Dict[str, Any]] = [{"text": improved_prompt_instruction}]
        for b64 in refs_b64:
            try:
                raw = base64.b64decode(b64)
                data, _fname, ctype = _prepare_ref_image_for_upload(raw)
                parts.append(
                    {
                        "inline_data": {
                            "mime_type": ctype,
                            "data": base64.b64encode(data).decode("ascii"),
                        }
                    }
                )
            except Exception:
                continue
        try:
            with httpx.Client(timeout=120) as client:
                response = client.post(
                    f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={token}",
                    headers={"Content-Type": "application/json"},
                    json={"contents": [{"parts": parts}]},
                )
                response.raise_for_status()
                data = response.json()
                candidates = data.get("candidates", [])
                if candidates:
                    gparts = candidates[0].get("content", {}).get("parts", [])
                    out_text = "".join(part.get("text", "") for part in gparts).strip()
                    return {"text": out_text or text}
                return {"text": text}
        except Exception as exc:
            raise HTTPException(status_code=502, detail=f"Google enhance error: {exc}")

    raise HTTPException(status_code=400, detail="Unsupported provider")
