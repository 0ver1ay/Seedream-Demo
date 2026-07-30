from __future__ import annotations

import os
import sys

if getattr(sys, "frozen", False):
    APP_DIR = os.path.dirname(sys.executable)
else:
    APP_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PROJECT_ROOT = os.path.dirname(APP_DIR)
for path in (APP_DIR, PROJECT_ROOT):
    if path not in sys.path:
        sys.path.insert(0, path)

LOG_FILE = os.path.join(APP_DIR, "log.txt")
SECRETS_FILE = os.path.join(APP_DIR, "secrets.json")
SESSION_FILE = os.path.join(APP_DIR, "session.json")

if getattr(sys, "frozen", False):
    os.environ["SEEDREAM_LOG_FILE"] = LOG_FILE
else:
    os.environ.setdefault("SEEDREAM_LOG_FILE", LOG_FILE)

STAGE_LABELS = {
    "prepare": "Подготовка",
    "upload_refs": "Загрузка референсов",
    "upload_done": "Референсы загружены",
    "predict": "Генерация",
    "predict_create": "Создание запроса",
    "predict_wait": "Ожидание модели",
    "predict_done": "Модель завершила работу",
    "download": "Скачивание",
    "done": "Готово",
    "error": "Ошибка",
    "parallel_start": "Параллельная генерация",
    "call_error": "Ошибка запроса",
}
