"""
Tests for the cross-domain transfer validation module.
"""

__classification__ = "UNCLASSIFIED"

import json
import os
import unittest
from unittest.mock import MagicMock, patch, PropertyMock

from sarpy.security.cross_domain_validation import (
    CrossDomainValidator,
    SecurityDomain,
    ValidationSeverity,
    TransferValidationReport,
    ValidationFinding,
    CLASSIFICATION_HIERARCHY,
    DOMAIN_MAX_CLASSIFICATION,
    check_file,
)


class TestSecurityDomain(unittest.TestCase):
    """Tests for SecurityDomain enum and classification mappings."""

    def test_domain_values(self):
        self.assertEqual(SecurityDomain.NIPRNET.value, "NIPRNET")
        self.assertEqual(SecurityDomain.SIPRNET.value, "SIPRNET")
        self.assertEqual(SecurityDomain.JWICS.value, "JWICS")
        self.assertEqual(SecurityDomain.COALNET.value, "COALNET")
        self.assertEqual(SecurityDomain.BICES.value, "BICES")

    def test_domain_max_classification(self):
        self.assertEqual(DOMAIN_MAX_CLASSIFICATION[SecurityDomain.NIPRNET], "U")
        self.assertEqual(DOMAIN_MAX_CLASSIFICATION[SecurityDomain.SIPRNET], "S")
        self.assertEqual(DOMAIN_MAX_CLASSIFICATION[SecurityDomain.JWICS], "T")
        self.assertEqual(DOMAIN_MAX_CLASSIFICATION[SecurityDomain.COALNET], "R")
        self.assertEqual(DOMAIN_MAX_CLASSIFICATION[SecurityDomain.BICES], "S")

    def test_classification_hierarchy_order(self):
        self.assertLess(CLASSIFICATION_HIERARCHY["U"], CLASSIFICATION_HIERARCHY["R"])
        self.assertLess(CLASSIFICATION_HIERARCHY["R"], CLASSIFICATION_HIERARCHY["C"])
        self.assertLess(CLASSIFICATION_HIERARCHY["C"], CLASSIFICATION_HIERARCHY["S"])
        self.assertLess(CLASSIFICATION_HIERARCHY["S"], CLASSIFICATION_HIERARCHY["T"])


class TestValidationFinding(unittest.TestCase):
    """Tests for ValidationFinding data class."""

    def test_finding_creation(self):
        finding = ValidationFinding(
            check_name="TEST_CHECK",
            severity=ValidationSeverity.CRITICAL,
            passed=True,
            message="Test passed",
            nist_control="AU-2",
        )
        self.assertEqual(finding.check_name, "TEST_CHECK")
        self.assertEqual(finding.severity, ValidationSeverity.CRITICAL)
        self.assertTrue(finding.passed)
        self.assertEqual(finding.nist_control, "AU-2")


class TestTransferValidationReport(unittest.TestCase):
    """Tests for TransferValidationReport data class."""

    def _make_report(self, findings=None):
        report = TransferValidationReport(
            file_path="/test/file.nitf",
            source_domain=SecurityDomain.SIPRNET,
            target_domain=SecurityDomain.JWICS,
        )
        if findings:
            report.findings = findings
        return report

    def test_report_passed_no_findings(self):
        report = self._make_report()
        self.assertTrue(report.passed)

    def test_report_passed_with_passing_critical(self):
        report = self._make_report([
            ValidationFinding("CHECK1", ValidationSeverity.CRITICAL, True, "ok"),
            ValidationFinding("CHECK2", ValidationSeverity.HIGH, True, "ok"),
        ])
        self.assertTrue(report.passed)

    def test_report_failed_with_critical_failure(self):
        report = self._make_report([
            ValidationFinding("CHECK1", ValidationSeverity.CRITICAL, False, "failed"),
        ])
        self.assertFalse(report.passed)

    def test_report_failed_with_high_failure(self):
        report = self._make_report([
            ValidationFinding("CHECK1", ValidationSeverity.HIGH, False, "failed"),
        ])
        self.assertFalse(report.passed)

    def test_report_passed_with_medium_failure(self):
        """Medium-severity failures should not block transfer."""
        report = self._make_report([
            ValidationFinding("CHECK1", ValidationSeverity.MEDIUM, False, "warning"),
        ])
        self.assertTrue(report.passed)

    def test_failure_reasons(self):
        report = self._make_report([
            ValidationFinding("CHECK1", ValidationSeverity.CRITICAL, False, "crit fail"),
            ValidationFinding("CHECK2", ValidationSeverity.HIGH, False, "high fail"),
            ValidationFinding("CHECK3", ValidationSeverity.MEDIUM, False, "med fail"),
        ])
        reasons = report.failure_reasons
        self.assertEqual(len(reasons), 2)
        self.assertIn("CHECK1: crit fail", reasons)
        self.assertIn("CHECK2: high fail", reasons)

    def test_counts(self):
        report = self._make_report([
            ValidationFinding("C1", ValidationSeverity.CRITICAL, False, ""),
            ValidationFinding("C2", ValidationSeverity.CRITICAL, False, ""),
            ValidationFinding("H1", ValidationSeverity.HIGH, False, ""),
            ValidationFinding("M1", ValidationSeverity.MEDIUM, False, ""),
        ])
        self.assertEqual(report.critical_count, 2)
        self.assertEqual(report.high_count, 1)
        self.assertEqual(report.medium_count, 1)

    def test_to_json(self):
        report = self._make_report([
            ValidationFinding("CHECK1", ValidationSeverity.CRITICAL, True, "ok", nist_control="AU-2"),
        ])
        report.file_hash_sha256 = "abc123"
        json_str = report.to_json()
        data = json.loads(json_str)
        self.assertEqual(data["report_type"], "cross_domain_transfer_validation")
        self.assertEqual(data["source_domain"], "SIPRNET")
        self.assertEqual(data["target_domain"], "JWICS")
        self.assertTrue(data["passed"])
        self.assertEqual(len(data["findings"]), 1)
        self.assertEqual(data["findings"][0]["nist_control"], "AU-2")


class TestCrossDomainValidator(unittest.TestCase):
    """Tests for CrossDomainValidator."""

    def test_init_with_string_domains(self):
        v = CrossDomainValidator(source_domain="SIPRNET", target_domain="JWICS")
        self.assertEqual(v.source_domain, SecurityDomain.SIPRNET)
        self.assertEqual(v.target_domain, SecurityDomain.JWICS)

    def test_init_with_enum_domains(self):
        v = CrossDomainValidator(
            source_domain=SecurityDomain.SIPRNET,
            target_domain=SecurityDomain.JWICS,
        )
        self.assertEqual(v.source_domain, SecurityDomain.SIPRNET)

    def test_init_case_insensitive(self):
        v = CrossDomainValidator(source_domain="siprnet", target_domain="jwics")
        self.assertEqual(v.source_domain, SecurityDomain.SIPRNET)

    def test_validate_nonexistent_file(self):
        v = CrossDomainValidator("SIPRNET", "JWICS")
        report = v.validate_file("/nonexistent/file.nitf")
        self.assertFalse(report.passed)
        self.assertTrue(any(
            f.check_name == "FILE_EXISTS" and not f.passed
            for f in report.findings
        ))

    def test_validate_domain_authorization_high_to_low(self):
        """Test that high-to-low transfers are flagged."""
        v = CrossDomainValidator("JWICS", "NIPRNET")
        report = TransferValidationReport(
            file_path="/test.nitf",
            source_domain=SecurityDomain.JWICS,
            target_domain=SecurityDomain.NIPRNET,
        )
        report.detected_classification = "U"
        v._validate_domain_authorization(report)
        auth_finding = next(
            f for f in report.findings
            if f.check_name == "TRANSFER_DIRECTION_AUTHORIZATION"
        )
        self.assertIn("HIGH-TO-LOW", auth_finding.message)

    def test_validate_domain_authorization_low_to_high(self):
        """Test that low-to-high transfers pass normally."""
        v = CrossDomainValidator("SIPRNET", "JWICS")
        report = TransferValidationReport(
            file_path="/test.nitf",
            source_domain=SecurityDomain.SIPRNET,
            target_domain=SecurityDomain.JWICS,
        )
        report.detected_classification = "S"
        v._validate_domain_authorization(report)
        auth_finding = next(
            f for f in report.findings
            if f.check_name == "TRANSFER_DIRECTION_AUTHORIZATION"
        )
        self.assertTrue(auth_finding.passed)

    def test_validate_classification_for_target_authorized(self):
        """Test file authorized for target domain."""
        v = CrossDomainValidator("SIPRNET", "JWICS")
        report = TransferValidationReport(
            file_path="/test.nitf",
            source_domain=SecurityDomain.SIPRNET,
            target_domain=SecurityDomain.JWICS,
        )
        report.detected_classification = "S"
        v._validate_classification_for_target(report)
        finding = next(f for f in report.findings if f.check_name == "TARGET_DOMAIN_AUTHORIZATION")
        self.assertTrue(finding.passed)

    def test_validate_classification_for_target_denied(self):
        """Test file NOT authorized for target domain (SECRET on NIPRNET)."""
        v = CrossDomainValidator("SIPRNET", "NIPRNET")
        report = TransferValidationReport(
            file_path="/test.nitf",
            source_domain=SecurityDomain.SIPRNET,
            target_domain=SecurityDomain.NIPRNET,
        )
        report.detected_classification = "S"
        v._validate_classification_for_target(report)
        finding = next(f for f in report.findings if f.check_name == "TARGET_DOMAIN_AUTHORIZATION")
        self.assertFalse(finding.passed)
        self.assertEqual(finding.severity, ValidationSeverity.CRITICAL)

    def test_validate_codeword_restrictions_coalition(self):
        """Test SCI codeword restrictions for coalition networks."""
        v = CrossDomainValidator("JWICS", "COALNET")
        report = TransferValidationReport(
            file_path="/test.nitf",
            source_domain=SecurityDomain.JWICS,
            target_domain=SecurityDomain.COALNET,
        )
        report.detected_classification = "S"
        report.detected_codewords = "TK SI"
        v._validate_codeword_restrictions(report)
        finding = next(f for f in report.findings if f.check_name == "CODEWORD_RESTRICTIONS")
        self.assertFalse(finding.passed)
        self.assertEqual(finding.severity, ValidationSeverity.CRITICAL)

    def test_validate_codeword_restrictions_no_codewords(self):
        """Test no codeword restrictions when none present."""
        v = CrossDomainValidator("SIPRNET", "JWICS")
        report = TransferValidationReport(
            file_path="/test.nitf",
            source_domain=SecurityDomain.SIPRNET,
            target_domain=SecurityDomain.JWICS,
        )
        report.detected_codewords = ""
        v._validate_codeword_restrictions(report)
        finding = next(f for f in report.findings if f.check_name == "CODEWORD_RESTRICTIONS")
        self.assertTrue(finding.passed)

    def test_validate_transfer_direction_source_violation(self):
        """Test detection of classification exceeding source domain."""
        v = CrossDomainValidator("NIPRNET", "JWICS")
        report = TransferValidationReport(
            file_path="/test.nitf",
            source_domain=SecurityDomain.NIPRNET,
            target_domain=SecurityDomain.JWICS,
        )
        report.detected_classification = "S"  # SECRET on NIPRNET = spill
        v._validate_transfer_direction(report)
        finding = next(f for f in report.findings if f.check_name == "SOURCE_DOMAIN_VIOLATION")
        self.assertFalse(finding.passed)
        self.assertEqual(finding.severity, ValidationSeverity.CRITICAL)
        self.assertIn("spill response", finding.remediation.lower())


class TestCheckFileFunction(unittest.TestCase):
    """Tests for the convenience check_file function."""

    def test_check_file_nonexistent(self):
        report = check_file("/nonexistent/file.nitf", output_json=False)
        self.assertFalse(report.passed)


if __name__ == '__main__':
    unittest.main()
