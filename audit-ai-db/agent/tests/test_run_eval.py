from __future__ import annotations

import unittest

from agent.run_eval import _string_list


class RunEvalTests(unittest.TestCase):
    def test_string_list_accepts_string_or_array(self) -> None:
        self.assertEqual(_string_list("負面資訊"), ["負面資訊"])
        self.assertEqual(_string_list(["負面資訊", "必要查證"]), ["負面資訊", "必要查證"])
        self.assertEqual(_string_list(None), [])


if __name__ == "__main__":
    unittest.main()
