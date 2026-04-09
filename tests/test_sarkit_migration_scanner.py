"""
Tests for the SarPy-to-SARKit migration scanner.
"""

import json
import os
import tempfile
import textwrap
import unittest

from sarpy.migration.sarkit_scanner import (
    BREAKING_API_CHANGES,
    SARPY_TO_SARKIT_MAP,
    BreakingChange,
    MigrationFinding,
    MigrationReport,
    MigrationRisk,
    SarPyImportVisitor,
    scan_directory,
    scan_file,
)


class TestMigrationRisk(unittest.TestCase):
    """Tests for the MigrationRisk enum."""

    def test_risk_values(self):
        self.assertEqual(MigrationRisk.CRITICAL.value, "CRITICAL")
        self.assertEqual(MigrationRisk.HIGH.value, "HIGH")
        self.assertEqual(MigrationRisk.MEDIUM.value, "MEDIUM")
        self.assertEqual(MigrationRisk.LOW.value, "LOW")

    def test_all_map_entries_have_valid_risk(self):
        for module, (_, risk, _) in SARPY_TO_SARKIT_MAP.items():
            self.assertIsInstance(risk, MigrationRisk, f"Bad risk for {module}")


class TestMigrationKnowledgeBase(unittest.TestCase):
    """Tests for the migration knowledge base completeness."""

    def test_core_modules_mapped(self):
        core_modules = [
            "sarpy.io.complex.sicd",
            "sarpy.io.complex.sicd_elements",
            "sarpy.io.general.nitf",
            "sarpy.geometry.point_projection",
            "sarpy.consistency",
        ]
        for mod in core_modules:
            self.assertIn(mod, SARPY_TO_SARKIT_MAP, f"Missing mapping for {mod}")

    def test_breaking_changes_documented(self):
        critical_symbols = [
            "open_complex",
            "SICDReader",
            "SICDWriter",
            "SICDType",
            "NITFDetails",
        ]
        for sym in critical_symbols:
            self.assertIn(sym, BREAKING_API_CHANGES, f"Missing breaking change for {sym}")

    def test_map_entries_have_sarkit_target(self):
        for module, (sarkit, _, _) in SARPY_TO_SARKIT_MAP.items():
            self.assertTrue(
                sarkit.startswith("sarkit"),
                f"{module} maps to '{sarkit}' which doesn't start with 'sarkit'",
            )


class TestMigrationFinding(unittest.TestCase):
    """Tests for the MigrationFinding dataclass."""

    def test_creation(self):
        finding = MigrationFinding(
            file_path="test.py",
            line_number=10,
            sarpy_module="sarpy.io.complex.sicd",
            imported_names=["SICDReader"],
            sarkit_equivalent="sarkit.standards.sicd.io",
            risk="CRITICAL",
            guidance="Replace SICDReader with sarkit.standards.sicd.io.open()",
        )
        self.assertEqual(finding.file_path, "test.py")
        self.assertEqual(finding.risk, "CRITICAL")
        self.assertEqual(finding.imported_names, ["SICDReader"])


class TestMigrationReport(unittest.TestCase):
    """Tests for the MigrationReport."""

    def _make_report(self, findings=None, breaking=None):
        return MigrationReport(
            scan_timestamp="2026-04-07T00:00:00+00:00",
            scanned_path="/test",
            total_files_scanned=10,
            files_with_sarpy_usage=3,
            findings=findings or [],
            breaking_changes=breaking or [],
        )

    def test_empty_report(self):
        report = self._make_report()
        self.assertEqual(report.critical_count, 0)
        self.assertEqual(report.high_count, 0)
        self.assertEqual(report.estimated_effort_hours, 0.0)

    def test_risk_counts(self):
        findings = [
            MigrationFinding("a.py", 1, "sarpy.io.complex.sicd", [], "", "CRITICAL", ""),
            MigrationFinding("a.py", 2, "sarpy.io.complex.sicd", [], "", "CRITICAL", ""),
            MigrationFinding("b.py", 1, "sarpy.io.complex.base", [], "", "HIGH", ""),
            MigrationFinding("c.py", 1, "sarpy.geometry", [], "", "MEDIUM", ""),
            MigrationFinding("d.py", 1, "sarpy.visualization", [], "", "LOW", ""),
        ]
        report = self._make_report(findings=findings)
        self.assertEqual(report.critical_count, 2)
        self.assertEqual(report.high_count, 1)
        self.assertEqual(report.medium_count, 1)
        self.assertEqual(report.low_count, 1)

    def test_effort_estimate(self):
        findings = [
            MigrationFinding("a.py", 1, "sarpy.io.complex.sicd", [], "", "CRITICAL", ""),
            MigrationFinding("b.py", 1, "sarpy.visualization", [], "", "LOW", ""),
        ]
        report = self._make_report(findings=findings)
        # CRITICAL = 8h, LOW = 0.5h
        self.assertAlmostEqual(report.estimated_effort_hours, 8.5)

    def test_json_export(self):
        findings = [
            MigrationFinding("a.py", 1, "sarpy.io.complex.sicd", ["SICDReader"], "sarkit.standards.sicd.io", "CRITICAL", "Replace reader"),
        ]
        report = self._make_report(findings=findings)
        json_str = report.to_json()
        data = json.loads(json_str)
        self.assertEqual(data["total_files_scanned"], 10)
        self.assertEqual(data["critical_count"], 1)
        self.assertEqual(data["estimated_effort_hours"], 8.0)
        self.assertEqual(len(data["findings"]), 1)
        self.assertEqual(data["findings"][0]["sarpy_module"], "sarpy.io.complex.sicd")

    def test_print_summary(self):
        """Verify print_summary runs without error."""
        findings = [
            MigrationFinding("a.py", 1, "sarpy.io.complex.sicd", ["SICDReader"], "sarkit.standards.sicd.io", "CRITICAL", "note"),
        ]
        report = self._make_report(findings=findings)
        # Should not raise
        report.print_summary()


class TestScanFile(unittest.TestCase):
    """Tests for scanning individual Python files."""

    def _write_temp_file(self, content):
        fd, path = tempfile.mkstemp(suffix=".py")
        with os.fdopen(fd, "w") as fh:
            fh.write(textwrap.dedent(content))
        return path

    def test_scan_sarpy_import(self):
        path = self._write_temp_file("""
            from sarpy.io.complex.sicd import SICDReader
            reader = SICDReader("test.nitf")
        """)
        try:
            findings, breaking = scan_file(path)
            self.assertEqual(len(findings), 1)
            self.assertEqual(findings[0].sarpy_module, "sarpy.io.complex.sicd")
            self.assertIn("SICDReader", findings[0].imported_names)
            self.assertEqual(findings[0].risk, "CRITICAL")
        finally:
            os.unlink(path)

    def test_scan_import_sarpy_module(self):
        path = self._write_temp_file("""
            import sarpy.io.complex.converter
        """)
        try:
            findings, breaking = scan_file(path)
            self.assertEqual(len(findings), 1)
            self.assertEqual(findings[0].sarpy_module, "sarpy.io.complex.converter")
        finally:
            os.unlink(path)

    def test_scan_multiple_imports(self):
        path = self._write_temp_file("""
            from sarpy.io.complex.sicd import SICDReader
            from sarpy.geometry.point_projection import image_to_ground
            from sarpy.io.general.nitf import NITFDetails
        """)
        try:
            findings, _ = scan_file(path)
            self.assertEqual(len(findings), 3)
            modules = {f.sarpy_module for f in findings}
            self.assertIn("sarpy.io.complex.sicd", modules)
            self.assertIn("sarpy.geometry.point_projection", modules)
            self.assertIn("sarpy.io.general.nitf", modules)
        finally:
            os.unlink(path)

    def test_scan_non_sarpy_import_ignored(self):
        path = self._write_temp_file("""
            import numpy as np
            from pathlib import Path
        """)
        try:
            findings, breaking = scan_file(path)
            self.assertEqual(len(findings), 0)
            self.assertEqual(len(breaking), 0)
        finally:
            os.unlink(path)

    def test_scan_breaking_change_detected(self):
        path = self._write_temp_file("""
            from sarpy.io.complex.converter import open_complex
            reader = open_complex("test.nitf")
        """)
        try:
            findings, breaking = scan_file(path)
            self.assertTrue(len(breaking) >= 1)
            symbols = {bc.symbol for bc in breaking}
            self.assertIn("open_complex", symbols)
        finally:
            os.unlink(path)

    def test_scan_syntax_error_file(self):
        path = self._write_temp_file("""
            def broken(
        """)
        try:
            findings, breaking = scan_file(path)
            self.assertEqual(len(findings), 0)
        finally:
            os.unlink(path)

    def test_scan_nonexistent_file(self):
        findings, breaking = scan_file("/nonexistent/file.py")
        self.assertEqual(len(findings), 0)


class TestScanDirectory(unittest.TestCase):
    """Tests for directory scanning."""

    def test_scan_directory_with_sarpy_files(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            # Create a file with sarpy imports
            with open(os.path.join(tmpdir, "processor.py"), "w") as fh:
                fh.write("from sarpy.io.complex.sicd import SICDReader\n")
                fh.write("from sarpy.consistency.sicd_consistency import check_file\n")

            # Create a clean file
            with open(os.path.join(tmpdir, "utils.py"), "w") as fh:
                fh.write("import os\n")

            report = scan_directory(tmpdir)
            self.assertEqual(report.total_files_scanned, 2)
            self.assertEqual(report.files_with_sarpy_usage, 1)
            self.assertTrue(len(report.findings) >= 2)

    def test_scan_directory_excludes_pycache(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            cache_dir = os.path.join(tmpdir, "__pycache__")
            os.makedirs(cache_dir)
            with open(os.path.join(cache_dir, "cached.py"), "w") as fh:
                fh.write("from sarpy.io.complex.sicd import SICDReader\n")

            report = scan_directory(tmpdir)
            self.assertEqual(report.total_files_scanned, 0)
            self.assertEqual(report.files_with_sarpy_usage, 0)

    def test_scan_empty_directory(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            report = scan_directory(tmpdir)
            self.assertEqual(report.total_files_scanned, 0)
            self.assertEqual(report.critical_count, 0)


class TestScanSarPyItself(unittest.TestCase):
    """Test scanning the sarpy codebase itself — the ultimate integration test."""

    def test_scan_sarpy_codebase(self):
        """Scan the sarpy package directory and verify non-trivial findings."""
        sarpy_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        sarpy_pkg = os.path.join(sarpy_dir, "sarpy")
        if not os.path.isdir(sarpy_pkg):
            self.skipTest("sarpy package directory not found")

        report = scan_directory(sarpy_pkg)
        # sarpy uses itself extensively — should find many imports
        self.assertGreater(report.total_files_scanned, 50)
        self.assertGreater(report.files_with_sarpy_usage, 20)
        self.assertGreater(len(report.findings), 50)
        # Should find critical items (SICD reader/writer are used internally)
        self.assertGreater(report.critical_count, 0)
        # JSON export should work
        json_str = report.to_json()
        data = json.loads(json_str)
        self.assertIn("findings", data)
        self.assertIn("estimated_effort_hours", data)


if __name__ == "__main__":
    unittest.main()
