"""Tests for the public import-probe helpers."""

import unittest
from unittest.mock import patch

from ssquant.api import debug_utils


class DebugUtilsImportProbeTests(unittest.TestCase):
    def test_missing_requested_module_returns_false(self):
        self.assertFalse(debug_utils.check_module_exists("missing_debug_probe_target"))
        self.assertFalse(
            debug_utils.check_function_exists(
                "missing_debug_probe_target", "anything"
            )
        )

    def test_missing_parent_of_requested_module_returns_false(self):
        module_name = "missing_debug_probe_parent.child"

        self.assertFalse(debug_utils.check_module_exists(module_name))
        self.assertFalse(
            debug_utils.check_function_exists(module_name, "anything")
        )

    def test_missing_dependency_inside_module_is_reraised(self):
        missing_dependency = ModuleNotFoundError(
            "No module named 'missing_debug_probe_dependency'",
            name="missing_debug_probe_dependency",
        )
        with patch.object(
            debug_utils.importlib,
            "import_module",
            side_effect=missing_dependency,
        ):
            with self.assertRaisesRegex(
                ModuleNotFoundError, "missing_debug_probe_dependency"
            ):
                debug_utils.check_module_exists("existing_debug_probe_target")

    def test_data_module_report_uses_package_qualified_names(self):
        with (
            patch.object(debug_utils, "check_module_exists", return_value=True),
            patch.object(debug_utils, "get_module_path", return_value="/module.py"),
            patch.object(debug_utils, "check_function_exists", return_value=True),
        ):
            report = debug_utils.check_data_modules()

        self.assertEqual(
            set(report["modules"]),
            {
                "ssquant.data.data_source",
                "ssquant.data.api_data_fetcher",
                "ssquant.data.multi_data_fetcher",
                "ssquant.api.strategy_api",
            },
        )
        self.assertEqual(
            set(report["functions"]),
            {
                "ssquant.data.api_data_fetcher.get_futures_data",
                "ssquant.data.multi_data_fetcher.fetch_multiple_data",
                "ssquant.api.strategy_api.create_strategy_api",
            },
        )
