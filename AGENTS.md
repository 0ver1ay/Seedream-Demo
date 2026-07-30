# Seedream — заметки для агентов

## Проверка

```powershell
cd C:\Work\Python\Seedream
pip install -r server/requirements.txt
python -m unittest discover -s tests -v
```

Live Replicate-тест (опционально): `SEEDREAM_RUN_LIVE_REPLICATE=1` и `REPLICATE_API_TOKEN`.

## Desktop

```powershell
cd desktop-app
python app.py
```

Сборка exe: `desktop-app/build_exe.ps1`

## Границы задач

| Поток | Файлы |
|-------|-------|
| Desktop UI | `desktop-app/seedream_desktop/`, `desktop-app/app.py` |
| Backend core | `server/core.py`, `tests/test_server_core.py` |
| HTTP API | `server/main.py` |
| Photoshop | `photoshop-plugin/` |

Один агент на `server/core.py` и один на `seedream_desktop/application.py` одновременно.

## Секреты

Не коммитить `secrets.json`, `session.json`, `log.txt`, `dist/`, `build/`. Шаблон: `desktop-app/secrets.example.json`.

## Desktop storage v3

Референсы хранятся в `seedream_assets/refs/` по `rel_path`. `session.json` содержит только метаданные и пути.

## HTTP-режим desktop

Если задан `SEEDREAM_SERVER` (env или в Настройках), desktop вызывает `POST /seedream/generate` и `/seedream/enhance` вместо прямого `server.core`.

## Структура UI

| Модуль | Назначение |
|--------|------------|
| `seedream_desktop/application.py` | Оркестратор |
| `seedream_desktop/views/pipeline_tree.py` | Дерево проекта |
| `seedream_desktop/views/preview_panel.py` | Превью и лента |
| `seedream_desktop/views/refs_panel.py` | Референсы + drag-reorder |
| `seedream_desktop/views/settings_dialog.py` | Настройки |
| `seedream_desktop/services/http_client.py` | HTTP backend |
| `seedream_desktop/services/session_restore.py` | Splash восстановления |
