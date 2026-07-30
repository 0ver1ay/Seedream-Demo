import os
import sys
import traceback
from uvicorn import run


def main() -> int:
    host = os.getenv("SEEDREAM_HOST", "0.0.0.0")
    port = int(os.getenv("SEEDREAM_PORT", "8000"))
    # Import app lazily to allow trial guard to initialize
    try:
        from server.main import app  # type: ignore
    except ModuleNotFoundError as im_err:
        # Only fall back if the failure is due to package/module layout,
        # not if an import inside server.main failed (surface that error).
        if im_err.name in {"server", "server.main"}:
            from main import app  # type: ignore
        else:
            raise
    run(app=app, host=host, port=port, reload=False, workers=1, log_level="info")
    return 0


if __name__ == "__main__":
    try:
        code = main()
    except Exception as exc:
        print("Fatal error while starting the server:", file=sys.stderr)
        print(str(exc), file=sys.stderr)
        traceback.print_exc()
        if getattr(sys, "frozen", False):
            try:
                input("Press Enter to exit...")
            except Exception:
                pass
        code = 1
    raise SystemExit(code)


