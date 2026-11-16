"""A wrong runtime should fail before dependency installation starts."""
import importlib.util
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import patch

spec = importlib.util.spec_from_file_location('check_runtime', Path(__file__).parents[1] / 'scripts/check_runtime.py')
runtime = importlib.util.module_from_spec(spec)
spec.loader.exec_module(runtime)


class RuntimeTests(unittest.TestCase):
    def test_wrong_python_has_an_interpreter_selection_hint(self):
        with patch.object(runtime.sys, 'version_info', (3, 10, 0)):
            with self.assertRaisesRegex(RuntimeError, 'Python 3.12.*Select Python'):
                runtime.check_runtime()

    def test_old_node_is_rejected_before_running_npm(self):
        with patch.object(runtime.shutil, 'which', return_value='node'), \
             patch.object(runtime.subprocess, 'run', return_value=SimpleNamespace(stdout='v22.12.0\n')):
            with self.assertRaisesRegex(RuntimeError, 'Node.js 24 or newer.*v22.12.0'):
                runtime.check_runtime()

    def test_missing_node_has_an_installation_hint(self):
        with patch.object(runtime.shutil, 'which', return_value=None):
            with self.assertRaisesRegex(RuntimeError, 'Install it and reopen'):
                runtime.check_runtime()

    def test_supported_runtime_is_accepted(self):
        with patch.object(runtime.shutil, 'which', return_value='runtime-command'), \
             patch.object(runtime.subprocess, 'run', return_value=SimpleNamespace(stdout='v24.22.0\n')):
            self.assertIn('Runtime ready:', runtime.check_runtime())
