import os
import sys
import unittest

DESKTOP_APP_DIR = os.path.normpath(os.path.join(os.path.dirname(__file__), "..", "desktop-app"))
if DESKTOP_APP_DIR not in sys.path:
    sys.path.insert(0, DESKTOP_APP_DIR)

from seedream_desktop.task_prompts import (
    append_task_iteration,
    create_task_prompt,
    find_task,
    normalize_task_prompts,
)


class TaskPromptsTests(unittest.TestCase):
    def test_create_and_find(self):
        task = create_task_prompt(name="Hero", prompt="a cat", prompt_enhanced="a sharp cat")
        self.assertTrue(str(task["id"]).startswith("task_"))
        self.assertEqual(task["name"], "Hero")
        self.assertEqual(len(task["iterations"]), 1)
        self.assertEqual(task["iterations"][0]["kind"], "create")
        found = find_task([task], task["id"])
        self.assertIs(found, task)

    def test_append_iteration_updates_current(self):
        task = create_task_prompt(name="T", prompt="v1")
        append_task_iteration(task, prompt="v2", prompt_enhanced="v2+", kind="enhance")
        self.assertEqual(task["prompt"], "v2")
        self.assertEqual(task["prompt_enhanced"], "v2+")
        self.assertEqual(task["iterations"][-1]["kind"], "enhance")
        self.assertEqual(len(task["iterations"]), 2)

    def test_normalize_keeps_last_40(self):
        raw = [
            {
                "id": "task_abc",
                "name": "X",
                "prompt": "p",
                "iterations": [{"prompt": f"i{i}", "kind": "edit"} for i in range(55)],
            }
        ]
        out = normalize_task_prompts(raw)
        self.assertEqual(len(out), 1)
        self.assertEqual(len(out[0]["iterations"]), 40)
        self.assertEqual(out[0]["iterations"][0]["prompt"], "i15")


if __name__ == "__main__":
    unittest.main()
