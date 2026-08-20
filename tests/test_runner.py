import importlib.util
import unittest
from unittest.mock import patch

import run_tests


class TestRunnerDependencyHandling(unittest.TestCase):
    def test_optional_layer_is_skipped_when_dependency_is_missing(self):
        with patch.object(run_tests.importlib.util, "find_spec", return_value=None):
            self.assertFalse(run_tests.layer_dependency_available("ui"))

    def test_core_layer_does_not_require_optional_dependency(self):
        self.assertTrue(run_tests.layer_dependency_available("core"))


if __name__ == "__main__":
    unittest.main()
