from __future__ import annotations

import os
import threading
import time
import traceback
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from typing import Any, Callable, Optional

from server.core import generate_images as _default_generate_images

ProgressCallback = Callable[[str, dict[str, Any]], None]
GenerateFn = Callable[[dict[str, Any]], dict[str, Any]]


def parallel_generation_workers() -> int:
    raw = os.environ.get("SEEDREAM_PARALLEL_GENERATIONS", "").strip()
    try:
        w = int(raw) if raw else 4
    except ValueError:
        w = 4
    return max(1, min(8, w))


@dataclass
class GenerationResult:
    images: list[str] = field(default_factory=list)
    failures: int = 0
    calls: int = 0
    elapsed_s: float = 0.0
    first_error: Exception | None = None
    cancelled: bool = False


class GenerationController:
    def __init__(self) -> None:
        self._cancel = threading.Event()
        self._busy = threading.Event()

    @property
    def is_busy(self) -> bool:
        return self._busy.is_set()

    def cancel(self) -> None:
        self._cancel.set()

    def reset_cancel(self) -> None:
        self._cancel.clear()

    def run(
        self,
        payload: dict[str, Any],
        *,
        calls: int,
        on_progress: ProgressCallback | None = None,
        on_partial: Callable[[list[str], int, int, int], None] | None = None,
        generate_fn: Optional[GenerateFn] = None,
    ) -> GenerationResult:
        self._busy.set()
        self.reset_cancel()
        t0 = time.perf_counter()
        result = GenerationResult(calls=calls)

        def _progress(stage: str, **fields: Any) -> None:
            if on_progress:
                on_progress(stage, fields)

        def _check_cancel() -> bool:
            if self._cancel.is_set():
                result.cancelled = True
                return True
            return False

        gen = generate_fn

        def _one_call(call_index: int) -> list[str]:
            if _check_cancel():
                return []
            _progress("predict", call_index=call_index, calls=calls)
            if gen is not None:
                out = gen(payload)
            else:
                out = _default_generate_images(
                    payload,
                    progress_callback=lambda stage, **kw: _progress(stage, call_index=call_index, **kw),
                    cancel_event=self._cancel,
                )
            images = out.get("images_base64") or ([out.get("image_base64")] if out.get("image_base64") else [])
            return [img for img in images if img]

        try:
            _progress("prepare", calls=calls, refs=len(payload.get("init_images_base64") or []))
            if _check_cancel():
                return result

            workers = min(parallel_generation_workers(), calls)
            combined: list[str] = []

            if calls == 1 or workers == 1:
                for idx in range(calls):
                    if _check_cancel():
                        break
                    try:
                        images = _one_call(idx + 1)
                        combined.extend(images)
                        if on_partial:
                            on_partial(images, idx + 1, calls, result.failures)
                    except Exception as exc:
                        result.failures += 1
                        if result.first_error is None:
                            result.first_error = exc
                        _progress("call_error", call_index=idx + 1, error=str(exc))
            else:
                _progress("parallel_start", workers=workers, calls=calls)
                with ThreadPoolExecutor(max_workers=workers) as ex:
                    futures = {ex.submit(_one_call, i + 1): i for i in range(calls)}
                    done = 0
                    for fut in as_completed(futures):
                        if _check_cancel():
                            for pending in futures:
                                pending.cancel()
                            break
                        slot = futures[fut]
                        done += 1
                        try:
                            images = fut.result()
                            combined.extend(images)
                            if on_partial:
                                on_partial(images, done, calls, result.failures)
                        except Exception as exc:
                            result.failures += 1
                            if result.first_error is None:
                                result.first_error = exc
                            _progress("call_error", call_index=slot + 1, error=str(exc))

            result.images = combined
            result.elapsed_s = time.perf_counter() - t0
            if not combined and not result.cancelled:
                if result.first_error is not None:
                    raise RuntimeError(f"Все запросы завершились ошибкой. Первый сбой: {result.first_error}")
                raise RuntimeError("No image in response")
            _progress("done", images=len(combined), failures=result.failures, elapsed_s=round(result.elapsed_s, 3))
            return result
        except Exception as exc:
            result.first_error = exc
            result.elapsed_s = time.perf_counter() - t0
            _progress("error", error=str(exc), traceback=traceback.format_exc())
            raise
        finally:
            self._busy.clear()
