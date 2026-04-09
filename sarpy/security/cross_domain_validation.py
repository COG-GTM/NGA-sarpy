"""
Cross-Domain Transfer Validation for SAR Data Files.

This module provides comprehensive validation of SAR data files prior to
cross-domain transfer between security enclaves (e.g., NIPRNet, SIPRNet,
JWICS). It validates classification markings, metadata integrity, and
generates structured audit reports per NIST 800-53 AU-2 and IC/DoD
security policies.

Usage
-----
Validate a single file::

    >>> from sarpy.security.cross_domain_validation import CrossDomainValidator
    >>> validator = CrossDomainValidator(source_domain='SIPRNET', target_domain='JWICS')
    >>> report = validator.validate_file('/path/to/sicd_file.nitf')
    >>> report.print_summary()

Batch validation::

    >>> reports = validator.validate_directory('/path/to/sar_data/')
    >>> for r in reports:
    ...     if not r.passed:
    ...         print(f"FAILED: {r.file_path} - {r.failure_reasons}")

Command-line usage::

    >>> python -m sarpy.security.cross_domain_validation --source SIPRNET --target JWICS /path/to/file.nitf
"""

__classification__ = "UNCLASSIFIED"
__author__ = "Cognition AI"

import datetime
import json
import logging
import os
import hashlib
import argparse
import sys
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import List, Optional, Dict, Tuple, Union

from sarpy.compliance import bytes_to_string
from sarpy.io.general.nitf import NITFDetails
from sarpy.io.general.nitf_elements.security import NITFSecurityTags
from sarpy.io.complex.sicd import SICDDetails, extract_clas
from sarpy.io.complex.sicd_elements.SICD import SICDType

logger = logging.getLogger(__name__)


class SecurityDomain(Enum):
    """Security domains/enclaves for cross-domain transfer."""
    NIPRNET = "NIPRNET"       # Unclassified
    SIPRNET = "SIPRNET"       # SECRET
    JWICS = "JWICS"           # TOP SECRET/SCI
    COALNET = "COALNET"       # Coalition network
    BICES = "BICES"           # Battlefield Information Collection


# Maximum classification level allowed on each domain
DOMAIN_MAX_CLASSIFICATION = {
    SecurityDomain.NIPRNET: "U",    # Unclassified only
    SecurityDomain.SIPRNET: "S",    # Up to SECRET
    SecurityDomain.JWICS: "T",      # Up to TOP SECRET/SCI
    SecurityDomain.COALNET: "R",    # Up to RESTRICTED
    SecurityDomain.BICES: "S",      # Up to SECRET (coalition)
}

# Classification hierarchy (higher index = more restrictive)
CLASSIFICATION_HIERARCHY = {
    "U": 0,   # Unclassified
    "R": 1,   # Restricted
    "C": 2,   # Confidential
    "S": 3,   # Secret
    "T": 4,   # Top Secret
}


class ValidationSeverity(Enum):
    """Severity level for validation findings."""
    CRITICAL = "CRITICAL"    # Transfer MUST NOT proceed
    HIGH = "HIGH"            # Transfer should not proceed without review
    MEDIUM = "MEDIUM"        # Issue requires attention
    LOW = "LOW"              # Informational finding
    INFO = "INFO"            # Informational only


@dataclass
class ValidationFinding:
    """A single validation finding from the cross-domain check."""
    check_name: str
    severity: ValidationSeverity
    passed: bool
    message: str
    details: str = ""
    nist_control: str = ""  # NIST 800-53 control reference
    remediation: str = ""


@dataclass
class TransferValidationReport:
    """Complete validation report for a cross-domain transfer request."""
    file_path: str
    source_domain: SecurityDomain
    target_domain: SecurityDomain
    timestamp: str = field(default_factory=lambda: datetime.datetime.now(datetime.timezone.utc).isoformat())
    findings: List[ValidationFinding] = field(default_factory=list)
    file_hash_sha256: str = ""
    file_size_bytes: int = 0
    detected_classification: str = ""
    detected_codewords: str = ""
    sicd_metadata_present: bool = False
    nitf_version: str = ""

    @property
    def passed(self) -> bool:
        """Transfer is approved only if no CRITICAL or HIGH findings failed."""
        return all(
            f.passed or f.severity not in (ValidationSeverity.CRITICAL, ValidationSeverity.HIGH)
            for f in self.findings
        )

    @property
    def failure_reasons(self) -> List[str]:
        """List of reasons the transfer failed validation."""
        return [
            f"{f.check_name}: {f.message}"
            for f in self.findings
            if not f.passed and f.severity in (ValidationSeverity.CRITICAL, ValidationSeverity.HIGH)
        ]

    @property
    def critical_count(self) -> int:
        return sum(1 for f in self.findings if not f.passed and f.severity == ValidationSeverity.CRITICAL)

    @property
    def high_count(self) -> int:
        return sum(1 for f in self.findings if not f.passed and f.severity == ValidationSeverity.HIGH)

    @property
    def medium_count(self) -> int:
        return sum(1 for f in self.findings if not f.passed and f.severity == ValidationSeverity.MEDIUM)

    def print_summary(self) -> None:
        """Print a human-readable summary of the validation report."""
        status = "APPROVED" if self.passed else "DENIED"
        print(f"\n{'='*72}")
        print(f"  CROSS-DOMAIN TRANSFER VALIDATION REPORT")
        print(f"{'='*72}")
        print(f"  Status:          {status}")
        print(f"  File:            {self.file_path}")
        print(f"  Source Domain:   {self.source_domain.value}")
        print(f"  Target Domain:  {self.target_domain.value}")
        print(f"  Classification: {self.detected_classification}")
        print(f"  Timestamp:       {self.timestamp}")
        print(f"  SHA-256:         {self.file_hash_sha256[:16]}..." if self.file_hash_sha256 else "")
        print(f"  File Size:       {self.file_size_bytes:,} bytes")
        print(f"  NITF Version:    {self.nitf_version}")
        print(f"  SICD Metadata:   {'Present' if self.sicd_metadata_present else 'Not Found'}")
        if self.detected_codewords:
            print(f"  Codewords:       {self.detected_codewords}")
        print(f"{'─'*72}")
        print(f"  Findings: {self.critical_count} Critical, {self.high_count} High, {self.medium_count} Medium")
        print(f"{'─'*72}")

        for finding in self.findings:
            icon = "PASS" if finding.passed else "FAIL"
            print(f"  [{icon}] [{finding.severity.value}] {finding.check_name}")
            print(f"         {finding.message}")
            if finding.nist_control:
                print(f"         NIST 800-53: {finding.nist_control}")
            if not finding.passed and finding.remediation:
                print(f"         Remediation: {finding.remediation}")
            if finding.details:
                for line in finding.details.split('\n'):
                    print(f"         {line}")

        print(f"{'='*72}\n")

    def to_json(self) -> str:
        """Export report as JSON for audit trail ingestion."""
        return json.dumps({
            "report_type": "cross_domain_transfer_validation",
            "file_path": self.file_path,
            "source_domain": self.source_domain.value,
            "target_domain": self.target_domain.value,
            "timestamp": self.timestamp,
            "passed": self.passed,
            "file_hash_sha256": self.file_hash_sha256,
            "file_size_bytes": self.file_size_bytes,
            "detected_classification": self.detected_classification,
            "detected_codewords": self.detected_codewords,
            "sicd_metadata_present": self.sicd_metadata_present,
            "nitf_version": self.nitf_version,
            "summary": {
                "critical": self.critical_count,
                "high": self.high_count,
                "medium": self.medium_count,
                "total_findings": len(self.findings),
            },
            "findings": [
                {
                    "check_name": f.check_name,
                    "severity": f.severity.value,
                    "passed": f.passed,
                    "message": f.message,
                    "details": f.details,
                    "nist_control": f.nist_control,
                    "remediation": f.remediation,
                }
                for f in self.findings
            ],
        }, indent=2)


class CrossDomainValidator:
    """
    Validates SAR data files for cross-domain transfer between security enclaves.

    This validator performs comprehensive checks on NITF/SICD files to ensure
    classification markings are consistent, metadata integrity is maintained,
    and the file is authorized for transfer to the target security domain.

    Parameters
    ----------
    source_domain : str or SecurityDomain
        The originating security domain (e.g., 'SIPRNET', 'JWICS')
    target_domain : str or SecurityDomain
        The destination security domain
    strict_mode : bool
        If True, treat warnings as errors (default: False)
    """

    def __init__(
        self,
        source_domain: Union[str, SecurityDomain],
        target_domain: Union[str, SecurityDomain],
        strict_mode: bool = False,
    ):
        if isinstance(source_domain, str):
            source_domain = SecurityDomain(source_domain.upper())
        if isinstance(target_domain, str):
            target_domain = SecurityDomain(target_domain.upper())

        self.source_domain = source_domain
        self.target_domain = target_domain
        self.strict_mode = strict_mode

        self._source_max = DOMAIN_MAX_CLASSIFICATION[self.source_domain]
        self._target_max = DOMAIN_MAX_CLASSIFICATION[self.target_domain]

    def validate_file(self, file_path: str) -> TransferValidationReport:
        """
        Perform full cross-domain transfer validation on a single file.

        Parameters
        ----------
        file_path : str
            Path to the NITF/SICD file to validate

        Returns
        -------
        TransferValidationReport
            Complete validation report with findings and pass/fail status
        """
        file_path = str(Path(file_path).resolve())
        report = TransferValidationReport(
            file_path=file_path,
            source_domain=self.source_domain,
            target_domain=self.target_domain,
        )

        # Phase 1: File-level checks
        if not self._check_file_exists(file_path, report):
            return report

        self._compute_file_hash(file_path, report)
        report.file_size_bytes = os.path.getsize(file_path)

        # Phase 2: NITF structure validation
        nitf_details = self._parse_nitf(file_path, report)
        if nitf_details is None:
            return report

        # Phase 3: Security marking validation
        self._validate_file_security_tags(nitf_details, report)
        self._validate_image_segment_security(nitf_details, report)
        self._validate_des_security(nitf_details, report)

        # Phase 4: SICD-specific validation
        sicd_details = self._parse_sicd(file_path, report)
        if sicd_details is not None:
            report.sicd_metadata_present = True
            self._validate_sicd_classification(sicd_details, report)
            self._validate_sicd_metadata_integrity(sicd_details, report)

        # Phase 5: Cross-domain policy checks
        self._validate_domain_authorization(report)
        self._validate_classification_for_target(report)
        self._validate_codeword_restrictions(report)
        self._validate_releasability(nitf_details, report)

        # Phase 6: Transfer direction validation
        self._validate_transfer_direction(report)

        return report

    def validate_directory(self, dir_path: str, extensions: Optional[List[str]] = None) -> List[TransferValidationReport]:
        """
        Validate all SAR data files in a directory.

        Parameters
        ----------
        dir_path : str
            Path to directory containing SAR data files
        extensions : list of str, optional
            File extensions to check (default: .nitf, .ntf, .sicd)

        Returns
        -------
        list of TransferValidationReport
        """
        if extensions is None:
            extensions = ['.nitf', '.ntf', '.sicd', '.NITF', '.NTF', '.SICD']

        reports = []
        dir_path = Path(dir_path)
        for ext in extensions:
            for file_path in dir_path.rglob(f'*{ext}'):
                reports.append(self.validate_file(str(file_path)))

        return reports

    # ── Phase 1: File-level checks ──────────────────────────────────────

    def _check_file_exists(self, file_path: str, report: TransferValidationReport) -> bool:
        """Verify the file exists and is readable."""
        exists = os.path.isfile(file_path)
        report.findings.append(ValidationFinding(
            check_name="FILE_EXISTS",
            severity=ValidationSeverity.CRITICAL,
            passed=exists,
            message=f"File {'exists and is accessible' if exists else 'not found or not accessible'}",
            nist_control="AU-2",
        ))
        return exists

    def _compute_file_hash(self, file_path: str, report: TransferValidationReport) -> None:
        """Compute SHA-256 hash for integrity verification and audit trail."""
        sha256 = hashlib.sha256()
        try:
            with open(file_path, 'rb') as f:
                for chunk in iter(lambda: f.read(8192), b''):
                    sha256.update(chunk)
            report.file_hash_sha256 = sha256.hexdigest()
            report.findings.append(ValidationFinding(
                check_name="FILE_INTEGRITY_HASH",
                severity=ValidationSeverity.INFO,
                passed=True,
                message=f"SHA-256: {report.file_hash_sha256}",
                nist_control="SI-7",
                details="Hash computed for chain-of-custody verification",
            ))
        except OSError as e:
            report.findings.append(ValidationFinding(
                check_name="FILE_INTEGRITY_HASH",
                severity=ValidationSeverity.HIGH,
                passed=False,
                message=f"Failed to compute file hash: {e}",
                nist_control="SI-7",
                remediation="Ensure file is readable and not corrupted",
            ))

    # ── Phase 2: NITF structure validation ──────────────────────────────

    def _parse_nitf(self, file_path: str, report: TransferValidationReport) -> Optional[NITFDetails]:
        """Parse the NITF container structure."""
        try:
            nitf = NITFDetails(file_path)
            version = getattr(nitf.nitf_header, 'FVER', 'Unknown')
            report.nitf_version = str(version)
            report.findings.append(ValidationFinding(
                check_name="NITF_STRUCTURE",
                severity=ValidationSeverity.CRITICAL,
                passed=True,
                message=f"Valid NITF container parsed successfully",
                nist_control="SC-28",
                details=f"NITF version: {version}",
            ))
            return nitf
        except Exception as e:
            report.findings.append(ValidationFinding(
                check_name="NITF_STRUCTURE",
                severity=ValidationSeverity.CRITICAL,
                passed=False,
                message=f"Failed to parse NITF structure: {e}",
                nist_control="SC-28",
                remediation="Verify file is a valid NITF 2.1 or 2.0 container",
            ))
            return None

    def _validate_file_security_tags(self, nitf: NITFDetails, report: TransferValidationReport) -> None:
        """Validate the file-level NITF security tags."""
        try:
            security = nitf.nitf_header.Security
            clas = security.CLAS.strip()

            if not clas:
                report.findings.append(ValidationFinding(
                    check_name="FILE_CLASSIFICATION_MARKING",
                    severity=ValidationSeverity.CRITICAL,
                    passed=False,
                    message="File-level classification marking is empty",
                    nist_control="AC-16",
                    remediation="Set CLAS field in NITF file header security tags",
                ))
                return

            report.detected_classification = clas
            valid_markings = {'U', 'R', 'C', 'S', 'T'}
            is_valid = clas in valid_markings
            report.findings.append(ValidationFinding(
                check_name="FILE_CLASSIFICATION_MARKING",
                severity=ValidationSeverity.CRITICAL,
                passed=is_valid,
                message=f"File classification: {clas} ({'valid' if is_valid else 'invalid marking'})",
                nist_control="AC-16",
                remediation="Classification must be one of: U, R, C, S, T" if not is_valid else "",
            ))

            # Check classification system
            clsy = security.CLSY.strip()
            if clas != 'U' and not clsy:
                report.findings.append(ValidationFinding(
                    check_name="CLASSIFICATION_SYSTEM",
                    severity=ValidationSeverity.MEDIUM,
                    passed=False,
                    message="Classified file missing classification system (CLSY) designation",
                    nist_control="AC-16",
                    remediation="Set CLSY field (e.g., 'US' for US national security system)",
                ))
            elif clsy:
                report.findings.append(ValidationFinding(
                    check_name="CLASSIFICATION_SYSTEM",
                    severity=ValidationSeverity.INFO,
                    passed=True,
                    message=f"Classification system: {clsy}",
                    nist_control="AC-16",
                ))

            # Check codewords
            code = security.CODE.strip()
            if code:
                report.detected_codewords = code
                report.findings.append(ValidationFinding(
                    check_name="CODEWORD_MARKING",
                    severity=ValidationSeverity.INFO,
                    passed=True,
                    message=f"Codewords present: {code}",
                    nist_control="AC-16",
                ))

            # Check declassification information
            if clas != 'U':
                dctp = security.DCTP.strip()
                if not dctp:
                    report.findings.append(ValidationFinding(
                        check_name="DECLASSIFICATION_INFO",
                        severity=ValidationSeverity.MEDIUM,
                        passed=False,
                        message="Classified file missing declassification type (DCTP)",
                        nist_control="AC-16",
                        remediation="Set declassification type: DD (date), DE (event), X (exempt), etc.",
                    ))

            # Check classification authority
            if clas != 'U':
                capt = security.CAPT.strip()
                caut = security.CAUT.strip()
                has_authority = bool(capt) or bool(caut)
                report.findings.append(ValidationFinding(
                    check_name="CLASSIFICATION_AUTHORITY",
                    severity=ValidationSeverity.MEDIUM if not has_authority else ValidationSeverity.INFO,
                    passed=has_authority,
                    message=f"Classification authority: {'present' if has_authority else 'missing'}",
                    nist_control="AC-16",
                    remediation="Classified data must have classification authority (CAPT/CAUT)" if not has_authority else "",
                ))

        except Exception as e:
            report.findings.append(ValidationFinding(
                check_name="FILE_CLASSIFICATION_MARKING",
                severity=ValidationSeverity.CRITICAL,
                passed=False,
                message=f"Error reading file security tags: {e}",
                nist_control="AC-16",
            ))

    def _validate_image_segment_security(self, nitf: NITFDetails, report: TransferValidationReport) -> None:
        """Validate security markings on each image segment match file-level markings."""
        try:
            img_headers = nitf.img_headers
            if img_headers is None or len(img_headers) == 0:
                report.findings.append(ValidationFinding(
                    check_name="IMAGE_SEGMENT_SECURITY",
                    severity=ValidationSeverity.HIGH,
                    passed=False,
                    message="No image segments found in NITF file",
                    nist_control="AC-16",
                ))
                return

            file_clas = report.detected_classification
            all_consistent = True
            details_lines = []

            for idx, img_header in enumerate(img_headers):
                img_security = img_header.Security
                img_clas = img_security.CLAS.strip()
                consistent = img_clas == file_clas
                if not consistent:
                    all_consistent = False
                    details_lines.append(
                        f"Image segment {idx}: CLAS='{img_clas}' (file-level: '{file_clas}')"
                    )

            report.findings.append(ValidationFinding(
                check_name="IMAGE_SEGMENT_SECURITY_CONSISTENCY",
                severity=ValidationSeverity.CRITICAL,
                passed=all_consistent,
                message=f"Image segment security markings {'consistent' if all_consistent else 'INCONSISTENT'} "
                        f"with file-level markings across {len(img_headers)} segment(s)",
                nist_control="AC-16",
                details='\n'.join(details_lines) if details_lines else "",
                remediation="All image segments must carry the same classification as the file header" if not all_consistent else "",
            ))
        except Exception as e:
            report.findings.append(ValidationFinding(
                check_name="IMAGE_SEGMENT_SECURITY_CONSISTENCY",
                severity=ValidationSeverity.HIGH,
                passed=False,
                message=f"Error validating image segment security: {e}",
                nist_control="AC-16",
            ))

    def _validate_des_security(self, nitf: NITFDetails, report: TransferValidationReport) -> None:
        """Validate security markings on Data Extension Segments."""
        try:
            des_subheader_offsets = nitf.des_subheader_offsets
            if des_subheader_offsets is None or des_subheader_offsets.size == 0:
                return  # No DES segments to check

            file_clas = report.detected_classification
            inconsistencies = []

            for i in range(des_subheader_offsets.size):
                subhead_bytes = nitf.get_des_subheader_bytes(i)
                # DES security tags start at a known offset in the subheader
                # Check if the classification in the DES matches file-level
                if len(subhead_bytes) > 25:
                    # The security section of a DES subheader
                    # DESID (25 bytes) then DSVER (2 bytes) then security
                    try:
                        from sarpy.io.general.nitf_elements.des import DataExtensionHeader
                        des_header = DataExtensionHeader.from_bytes(subhead_bytes, start=0)
                        des_clas = des_header.Security.CLAS.strip()
                        if des_clas and des_clas != file_clas:
                            inconsistencies.append(
                                f"DES {i}: CLAS='{des_clas}' (file-level: '{file_clas}')"
                            )
                    except Exception:
                        pass  # Some DES may not follow standard format

            if inconsistencies:
                report.findings.append(ValidationFinding(
                    check_name="DES_SECURITY_CONSISTENCY",
                    severity=ValidationSeverity.HIGH,
                    passed=False,
                    message=f"Data Extension Segment security markings inconsistent",
                    nist_control="AC-16",
                    details='\n'.join(inconsistencies),
                    remediation="DES security markings must match file-level classification",
                ))
            else:
                report.findings.append(ValidationFinding(
                    check_name="DES_SECURITY_CONSISTENCY",
                    severity=ValidationSeverity.INFO,
                    passed=True,
                    message="Data Extension Segment security markings consistent",
                    nist_control="AC-16",
                ))
        except Exception as e:
            logger.debug(f"DES security validation skipped: {e}")

    # ── Phase 4: SICD-specific validation ───────────────────────────────

    def _parse_sicd(self, file_path: str, report: TransferValidationReport) -> Optional[SICDDetails]:
        """Attempt to parse file as SICD."""
        try:
            sicd = SICDDetails(file_path)
            if sicd.is_sicd:
                report.findings.append(ValidationFinding(
                    check_name="SICD_STRUCTURE",
                    severity=ValidationSeverity.INFO,
                    passed=True,
                    message="Valid SICD structure detected",
                    nist_control="SC-28",
                ))
                return sicd
        except Exception:
            pass  # File may be a non-SICD NITF, which is fine
        return None

    def _validate_sicd_classification(self, sicd: SICDDetails, report: TransferValidationReport) -> None:
        """Validate SICD XML metadata classification matches NITF security tags."""
        try:
            sicd_meta = sicd.sicd_meta
            sicd_clas = extract_clas(sicd_meta)
            file_clas = report.detected_classification

            consistent = sicd_clas == file_clas
            report.findings.append(ValidationFinding(
                check_name="SICD_CLASSIFICATION_CONSISTENCY",
                severity=ValidationSeverity.CRITICAL,
                passed=consistent,
                message=f"SICD XML classification ('{sicd_clas}') "
                        f"{'matches' if consistent else 'DOES NOT MATCH'} "
                        f"NITF file header ('{file_clas}')",
                nist_control="AC-16",
                remediation="SICD CollectionInfo.Classification must match NITF file header CLAS" if not consistent else "",
            ))

            # Check CollectionInfo details
            if sicd_meta.CollectionInfo is not None:
                classification_str = sicd_meta.CollectionInfo.Classification or ""
                report.findings.append(ValidationFinding(
                    check_name="SICD_CLASSIFICATION_STRING",
                    severity=ValidationSeverity.INFO,
                    passed=True,
                    message=f"SICD CollectionInfo.Classification: '{classification_str}'",
                    nist_control="AC-16",
                ))
        except Exception as e:
            report.findings.append(ValidationFinding(
                check_name="SICD_CLASSIFICATION_CONSISTENCY",
                severity=ValidationSeverity.HIGH,
                passed=False,
                message=f"Error validating SICD classification: {e}",
                nist_control="AC-16",
            ))

    def _validate_sicd_metadata_integrity(self, sicd: SICDDetails, report: TransferValidationReport) -> None:
        """Validate SICD metadata completeness and integrity."""
        try:
            meta = sicd.sicd_meta
            checks = []

            # CollectionInfo
            if meta.CollectionInfo is not None:
                checks.append(("CollectionInfo", True))
                if meta.CollectionInfo.CoreName:
                    checks.append(("CollectionInfo.CoreName", True))
                else:
                    checks.append(("CollectionInfo.CoreName", False))
            else:
                checks.append(("CollectionInfo", False))

            # ImageData
            if meta.ImageData is not None:
                checks.append(("ImageData", True))
                if meta.ImageData.NumRows and meta.ImageData.NumCols:
                    checks.append(("ImageData dimensions", True))
                else:
                    checks.append(("ImageData dimensions", False))
            else:
                checks.append(("ImageData", False))

            # GeoData
            if meta.GeoData is not None:
                checks.append(("GeoData", True))
            else:
                checks.append(("GeoData", False))

            missing = [name for name, present in checks if not present]
            all_present = len(missing) == 0

            report.findings.append(ValidationFinding(
                check_name="SICD_METADATA_INTEGRITY",
                severity=ValidationSeverity.MEDIUM,
                passed=all_present,
                message=f"SICD metadata integrity: {len(checks) - len(missing)}/{len(checks)} required fields present",
                nist_control="SI-7",
                details=f"Missing: {', '.join(missing)}" if missing else "All required metadata fields present",
                remediation="Populate missing SICD metadata fields before transfer" if missing else "",
            ))
        except Exception as e:
            report.findings.append(ValidationFinding(
                check_name="SICD_METADATA_INTEGRITY",
                severity=ValidationSeverity.MEDIUM,
                passed=False,
                message=f"Error checking SICD metadata integrity: {e}",
                nist_control="SI-7",
            ))

    # ── Phase 5: Cross-domain policy checks ─────────────────────────────

    def _validate_domain_authorization(self, report: TransferValidationReport) -> None:
        """Verify the transfer direction is authorized by policy."""
        source_level = CLASSIFICATION_HIERARCHY.get(self._source_max, -1)
        target_level = CLASSIFICATION_HIERARCHY.get(self._target_max, -1)

        # Transfers from higher to lower classification domains require review
        if source_level > target_level:
            report.findings.append(ValidationFinding(
                check_name="TRANSFER_DIRECTION_AUTHORIZATION",
                severity=ValidationSeverity.HIGH,
                passed=True,  # Not a failure, but requires additional review
                message=f"HIGH-TO-LOW transfer detected: {self.source_domain.value} → {self.target_domain.value}",
                nist_control="AC-4",
                details="Transfers from higher to lower classification domains require "
                        "Cross Domain Solution (CDS) review and approval. "
                        "This validator confirms marking consistency but does not "
                        "replace CDS adjudication.",
            ))
        else:
            report.findings.append(ValidationFinding(
                check_name="TRANSFER_DIRECTION_AUTHORIZATION",
                severity=ValidationSeverity.INFO,
                passed=True,
                message=f"Transfer direction: {self.source_domain.value} → {self.target_domain.value}",
                nist_control="AC-4",
            ))

    def _validate_classification_for_target(self, report: TransferValidationReport) -> None:
        """Verify the file's classification is authorized on the target domain."""
        file_clas = report.detected_classification
        if not file_clas:
            report.findings.append(ValidationFinding(
                check_name="TARGET_DOMAIN_AUTHORIZATION",
                severity=ValidationSeverity.CRITICAL,
                passed=False,
                message="Cannot validate target authorization: no classification detected",
                nist_control="AC-4",
            ))
            return

        file_level = CLASSIFICATION_HIERARCHY.get(file_clas, -1)
        target_level = CLASSIFICATION_HIERARCHY.get(self._target_max, -1)

        authorized = file_level <= target_level
        report.findings.append(ValidationFinding(
            check_name="TARGET_DOMAIN_AUTHORIZATION",
            severity=ValidationSeverity.CRITICAL,
            passed=authorized,
            message=f"File classification '{file_clas}' is "
                    f"{'authorized' if authorized else 'NOT AUTHORIZED'} "
                    f"for {self.target_domain.value} (max: '{self._target_max}')",
            nist_control="AC-4",
            remediation=f"File classified at '{file_clas}' exceeds {self.target_domain.value} "
                        f"maximum classification of '{self._target_max}'. "
                        f"Transfer DENIED." if not authorized else "",
        ))

    def _validate_codeword_restrictions(self, report: TransferValidationReport) -> None:
        """Check for SCI/SAP codewords that restrict cross-domain transfer."""
        codewords = report.detected_codewords
        if not codewords:
            report.findings.append(ValidationFinding(
                check_name="CODEWORD_RESTRICTIONS",
                severity=ValidationSeverity.INFO,
                passed=True,
                message="No compartmented codewords detected",
                nist_control="AC-4",
            ))
            return

        # SCI compartments that restrict transfer to certain domains
        restricted_for_coalition = {'TK', 'SI', 'G', 'HCS'}
        found_codewords = set(codewords.split())

        if self.target_domain in (SecurityDomain.COALNET, SecurityDomain.BICES):
            restricted_found = found_codewords.intersection(restricted_for_coalition)
            if restricted_found:
                report.findings.append(ValidationFinding(
                    check_name="CODEWORD_RESTRICTIONS",
                    severity=ValidationSeverity.CRITICAL,
                    passed=False,
                    message=f"SCI compartments {restricted_found} are NOT releasable to coalition networks",
                    nist_control="AC-4",
                    remediation="Files with these compartments cannot be transferred to coalition domains",
                ))
                return

        report.findings.append(ValidationFinding(
            check_name="CODEWORD_RESTRICTIONS",
            severity=ValidationSeverity.INFO,
            passed=True,
            message=f"Codewords '{codewords}' evaluated — no transfer restrictions identified",
            nist_control="AC-4",
        ))

    def _validate_releasability(self, nitf: NITFDetails, report: TransferValidationReport) -> None:
        """Check releasability markings against target domain."""
        try:
            rel = nitf.nitf_header.Security.REL.strip()
            if not rel:
                if report.detected_classification == 'U':
                    report.findings.append(ValidationFinding(
                        check_name="RELEASABILITY",
                        severity=ValidationSeverity.INFO,
                        passed=True,
                        message="Unclassified — no releasability restrictions apply",
                        nist_control="AC-16",
                    ))
                else:
                    report.findings.append(ValidationFinding(
                        check_name="RELEASABILITY",
                        severity=ValidationSeverity.MEDIUM,
                        passed=False,
                        message="Classified file missing releasability marking (REL field)",
                        nist_control="AC-16",
                        remediation="Set REL field with authorized release countries (e.g., 'USA', 'USA GBR AUS CAN NZL')",
                    ))
            else:
                report.findings.append(ValidationFinding(
                    check_name="RELEASABILITY",
                    severity=ValidationSeverity.INFO,
                    passed=True,
                    message=f"Releasability: {rel}",
                    nist_control="AC-16",
                ))

                # Check if target domain is a coalition network
                if self.target_domain in (SecurityDomain.COALNET, SecurityDomain.BICES):
                    if 'USA' in rel and len(rel.split()) == 1:
                        report.findings.append(ValidationFinding(
                            check_name="COALITION_RELEASABILITY",
                            severity=ValidationSeverity.HIGH,
                            passed=False,
                            message="File is marked REL TO USA only — not releasable to coalition networks",
                            nist_control="AC-4",
                            remediation="File must be marked with coalition partner country codes for coalition transfer",
                        ))
        except Exception as e:
            logger.debug(f"Releasability check skipped: {e}")

    # ── Phase 6: Transfer direction validation ──────────────────────────

    def _validate_transfer_direction(self, report: TransferValidationReport) -> None:
        """Final validation of the transfer direction and classification combination."""
        file_clas = report.detected_classification
        source_max_level = CLASSIFICATION_HIERARCHY.get(self._source_max, -1)
        target_max_level = CLASSIFICATION_HIERARCHY.get(self._target_max, -1)
        file_level = CLASSIFICATION_HIERARCHY.get(file_clas, -1)

        # Check: file classification exceeds source domain max (data shouldn't be here)
        if file_level > source_max_level:
            report.findings.append(ValidationFinding(
                check_name="SOURCE_DOMAIN_VIOLATION",
                severity=ValidationSeverity.CRITICAL,
                passed=False,
                message=f"File classified at '{file_clas}' EXCEEDS source domain "
                        f"{self.source_domain.value} maximum of '{self._source_max}'",
                nist_control="AC-3",
                remediation="This file should not exist on the source domain. "
                            "Initiate spill response procedures per IC policy.",
            ))
        else:
            report.findings.append(ValidationFinding(
                check_name="SOURCE_DOMAIN_COMPLIANCE",
                severity=ValidationSeverity.INFO,
                passed=True,
                message=f"File classification '{file_clas}' is appropriate for "
                        f"source domain {self.source_domain.value}",
                nist_control="AC-3",
            ))


def check_file(
    file_path: str,
    source_domain: str = "SIPRNET",
    target_domain: str = "JWICS",
    output_json: bool = False,
) -> TransferValidationReport:
    """
    Convenience function to validate a single file for cross-domain transfer.

    Parameters
    ----------
    file_path : str
        Path to the NITF/SICD file
    source_domain : str
        Source security domain (default: SIPRNET)
    target_domain : str
        Target security domain (default: JWICS)
    output_json : bool
        If True, print JSON report to stdout

    Returns
    -------
    TransferValidationReport
    """
    validator = CrossDomainValidator(
        source_domain=source_domain,
        target_domain=target_domain,
    )
    report = validator.validate_file(file_path)

    if output_json:
        print(report.to_json())
    else:
        report.print_summary()

    return report


def main():
    """Command-line entry point for cross-domain transfer validation."""
    parser = argparse.ArgumentParser(
        description="Validate SAR data files for cross-domain transfer between security enclaves",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  Validate a file for SIPRNET → JWICS transfer:
    python -m sarpy.security.cross_domain_validation --source SIPRNET --target JWICS file.nitf

  Validate a directory of files:
    python -m sarpy.security.cross_domain_validation --source JWICS --target SIPRNET --dir /data/sar/

  Output JSON report for audit ingestion:
    python -m sarpy.security.cross_domain_validation --json --source SIPRNET --target JWICS file.nitf

Security Domains:
  NIPRNET   - Unclassified (U)
  SIPRNET   - Up to SECRET (S)
  JWICS     - Up to TOP SECRET/SCI (T)
  COALNET   - Coalition network (R)
  BICES     - Battlefield Information Collection (S)
        """
    )

    parser.add_argument('files', nargs='*', help='NITF/SICD files to validate')
    parser.add_argument('--source', '-s', required=True,
                        choices=['NIPRNET', 'SIPRNET', 'JWICS', 'COALNET', 'BICES'],
                        help='Source security domain')
    parser.add_argument('--target', '-t', required=True,
                        choices=['NIPRNET', 'SIPRNET', 'JWICS', 'COALNET', 'BICES'],
                        help='Target security domain')
    parser.add_argument('--dir', '-d', help='Directory to scan for SAR files')
    parser.add_argument('--json', '-j', action='store_true', help='Output JSON report')
    parser.add_argument('--strict', action='store_true', help='Strict mode (warnings become errors)')

    args = parser.parse_args()

    if not args.files and not args.dir:
        parser.error("Provide file(s) or --dir to validate")

    validator = CrossDomainValidator(
        source_domain=args.source,
        target_domain=args.target,
        strict_mode=args.strict,
    )

    reports = []

    if args.dir:
        reports.extend(validator.validate_directory(args.dir))

    for file_path in (args.files or []):
        reports.append(validator.validate_file(file_path))

    exit_code = 0
    for report in reports:
        if args.json:
            print(report.to_json())
        else:
            report.print_summary()
        if not report.passed:
            exit_code = 1

    sys.exit(exit_code)


if __name__ == '__main__':
    main()
