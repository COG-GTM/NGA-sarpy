"""
SarPy-to-SARKit Migration Assessment Scanner.

Scans Python source trees for SarPy API usage and produces a prioritized
migration report mapping each call-site to its SARKit equivalent (or
flagging it as having no direct replacement yet).

NGA deprecated SarPy on 29 Jan 2026.  SARKit is the designated successor
for SAR data I/O, SICD/SIDD metadata handling, and GEOINT processing
within the NGA ecosystem.

Usage::

    python -m sarpy.migration /path/to/project

The scanner produces:

* Per-file import and call-site inventory
* Risk-rated migration items (CRITICAL / HIGH / MEDIUM / LOW)
* Estimated effort breakdown
* Machine-readable JSON export for ingestion into project-tracking tools

References
----------
- NGA/SIG SARKit repository (successor to SarPy)
- NIS 3101 SICD standard, NIS 3201 SIDD standard
"""

__classification__ = "UNCLASSIFIED"

import ast
import os
import sys
import json
import argparse
import datetime
from dataclasses import dataclass, field, asdict
from enum import Enum
from pathlib import Path
from typing import List, Dict, Optional, Tuple


# ---------------------------------------------------------------------------
# Migration knowledge base
# ---------------------------------------------------------------------------

class MigrationRisk(Enum):
    """Risk level for a migration item."""
    CRITICAL = "CRITICAL"
    HIGH = "HIGH"
    MEDIUM = "MEDIUM"
    LOW = "LOW"


# Mapping of sarpy module paths to SARKit equivalents and migration guidance.
# Each entry: (sarkit_module, risk, migration_note)
SARPY_TO_SARKIT_MAP: Dict[str, Tuple[str, MigrationRisk, str]] = {
    # ---- Core I/O ----
    "sarpy.io.complex.sicd": (
        "sarkit.standards.sicd.io",
        MigrationRisk.CRITICAL,
        "SICD reader/writer are central to most workflows. SARKit moves "
        "these into sarkit.standards.sicd.io with a new reader API that "
        "returns xarray Datasets instead of numpy arrays.",
    ),
    "sarpy.io.complex.converter": (
        "sarkit.standards.sicd.io",
        MigrationRisk.HIGH,
        "Converter and open_complex() are replaced by sarkit.standards."
        "sicd.io.open() which auto-detects format. The Converter class "
        "is replaced by sarkit.standards.sicd.io.write().",
    ),
    "sarpy.io.complex.sicd_elements": (
        "sarkit.standards.sicd",
        MigrationRisk.CRITICAL,
        "The entire SICD element tree (CollectionInfo, GeoData, Grid, "
        "etc.) moves to sarkit.standards.sicd and uses dataclass-based "
        "structures instead of the custom Serializable framework.",
    ),
    "sarpy.io.complex.sicd_elements.SICD": (
        "sarkit.standards.sicd.SICDType",
        MigrationRisk.CRITICAL,
        "SICDType is the root metadata object. In SARKit it is a "
        "dataclass with typed fields. The .derive() and .is_valid() "
        "methods have new signatures.",
    ),
    "sarpy.io.complex.sicd_elements.CollectionInfo": (
        "sarkit.standards.sicd.CollectionInfo",
        MigrationRisk.MEDIUM,
        "CollectionInfoType maps directly. Field names are identical "
        "but the descriptor system is replaced by standard Python "
        "dataclasses.",
    ),
    "sarpy.io.complex.sicd_elements.GeoData": (
        "sarkit.standards.sicd.GeoData",
        MigrationRisk.MEDIUM,
        "GeoDataType maps directly. SCP coordinates use numpy arrays "
        "instead of the custom ECF/LLH wrapper classes.",
    ),
    "sarpy.io.complex.sicd_elements.ImageData": (
        "sarkit.standards.sicd.ImageData",
        MigrationRisk.MEDIUM,
        "ImageDataType maps directly with simplified pixel-type "
        "handling.",
    ),
    "sarpy.io.complex.sicd_elements.Grid": (
        "sarkit.standards.sicd.Grid",
        MigrationRisk.MEDIUM,
        "GridType maps directly. Weight function handling is simplified.",
    ),
    "sarpy.io.complex.sicd_schema": (
        "sarkit.standards.sicd.schema",
        MigrationRisk.LOW,
        "Schema utilities are internalized in SARKit. External access "
        "through sarkit.standards.sicd.schema.",
    ),
    "sarpy.io.complex.base": (
        "sarkit.io.base",
        MigrationRisk.HIGH,
        "SICDTypeReader base class is replaced by sarkit.io.base."
        "ComplexReader. Subclassing interface has changed.",
    ),
    # ---- Vendor-specific readers ----
    "sarpy.io.complex.sentinel": (
        "sarkit.io.sentinel",
        MigrationRisk.HIGH,
        "Sentinel-1 reader relocated. API returns xarray Datasets.",
    ),
    "sarpy.io.complex.capella": (
        "sarkit.io.capella",
        MigrationRisk.HIGH,
        "Capella reader relocated. API returns xarray Datasets.",
    ),
    "sarpy.io.complex.iceye": (
        "sarkit.io.iceye",
        MigrationRisk.HIGH,
        "ICEYE reader relocated. API returns xarray Datasets.",
    ),
    "sarpy.io.complex.tsx": (
        "sarkit.io.tsx",
        MigrationRisk.HIGH,
        "TerraSAR-X reader relocated. API returns xarray Datasets.",
    ),
    "sarpy.io.complex.radarsat": (
        "sarkit.io.radarsat",
        MigrationRisk.HIGH,
        "RADARSAT reader relocated. API returns xarray Datasets.",
    ),
    "sarpy.io.complex.csk": (
        "sarkit.io.cosmo",
        MigrationRisk.HIGH,
        "COSMO-SkyMed reader relocated and renamed.",
    ),
    # ---- NITF ----
    "sarpy.io.general.nitf": (
        "sarkit.io.nitf",
        MigrationRisk.CRITICAL,
        "NITFDetails and NITFReader are core to cross-domain workflows. "
        "SARKit uses sarkit.io.nitf with a modernized header API.",
    ),
    "sarpy.io.general.nitf_elements": (
        "sarkit.io.nitf.elements",
        MigrationRisk.HIGH,
        "NITF header/segment element classes relocated.",
    ),
    # ---- SIDD (product) ----
    "sarpy.io.product": (
        "sarkit.standards.sidd",
        MigrationRisk.HIGH,
        "SIDD product readers/writers move to sarkit.standards.sidd.",
    ),
    "sarpy.io.product.sidd2_elements": (
        "sarkit.standards.sidd",
        MigrationRisk.HIGH,
        "SIDD element tree moves to sarkit.standards.sidd with "
        "dataclass structures.",
    ),
    # ---- CPHD / CRSD ----
    "sarpy.io.phase_history": (
        "sarkit.standards.cphd",
        MigrationRisk.HIGH,
        "CPHD reader/writer moves to sarkit.standards.cphd.",
    ),
    "sarpy.io.received": (
        "sarkit.standards.crsd",
        MigrationRisk.MEDIUM,
        "CRSD reader/writer moves to sarkit.standards.crsd.",
    ),
    # ---- Geometry & projection ----
    "sarpy.geometry.point_projection": (
        "sarkit.geometry.projection",
        MigrationRisk.MEDIUM,
        "Point projection utilities are largely API-compatible. "
        "Function signatures gain optional keyword arguments.",
    ),
    "sarpy.geometry.geocoords": (
        "sarkit.geometry.coordinates",
        MigrationRisk.LOW,
        "Coordinate conversion functions have identical signatures.",
    ),
    "sarpy.geometry.geometry_elements": (
        "sarkit.geometry.shapes",
        MigrationRisk.LOW,
        "Geometry element classes renamed to standard shape types.",
    ),
    # ---- Processing ----
    "sarpy.processing.sicd": (
        "sarkit.processing.complex",
        MigrationRisk.MEDIUM,
        "SICD processing (subaperture, CSI, CCD) moves to "
        "sarkit.processing.complex with numpy/xarray APIs.",
    ),
    "sarpy.processing.ortho_rectify": (
        "sarkit.processing.ortho",
        MigrationRisk.MEDIUM,
        "Orthorectification moves to sarkit.processing.ortho.",
    ),
    # ---- Consistency / validation ----
    "sarpy.consistency": (
        "sarkit.validation",
        MigrationRisk.LOW,
        "Validation modules move to sarkit.validation with expanded "
        "checks.",
    ),
    "sarpy.consistency.sicd_consistency": (
        "sarkit.validation.sicd",
        MigrationRisk.LOW,
        "SICD consistency checks move to sarkit.validation.sicd.",
    ),
    # ---- Visualization ----
    "sarpy.visualization": (
        "sarkit.visualization",
        MigrationRisk.LOW,
        "Visualization utilities are largely unchanged.",
    ),
    # ---- XML framework ----
    "sarpy.io.xml": (
        "sarkit.io.xml",
        MigrationRisk.HIGH,
        "The custom Serializable/descriptor XML framework is replaced "
        "by standard dataclasses with lxml serialization helpers. "
        "Direct Serializable subclasses require rewrite.",
    ),
    "sarpy.io.xml.base": (
        "sarkit.io.xml",
        MigrationRisk.HIGH,
        "Serializable base class removed. Use Python dataclasses and "
        "sarkit.io.xml.to_xml() / sarkit.io.xml.from_xml() helpers.",
    ),
    # ---- Annotation ----
    "sarpy.annotation": (
        "sarkit.annotation",
        MigrationRisk.LOW,
        "Annotation framework is largely unchanged.",
    ),
}

# Functions/classes with known API changes that need special attention
BREAKING_API_CHANGES: Dict[str, Tuple[str, str]] = {
    "open_complex": (
        "sarkit.standards.sicd.io.open",
        "Returns xarray.Dataset instead of SICDTypeReader. "
        "Indexing changes from reader[row, col] to ds.complex_data[row, col].",
    ),
    "SICDReader": (
        "sarkit.standards.sicd.io.open",
        "Replaced by functional API. No direct class equivalent.",
    ),
    "SICDWriter": (
        "sarkit.standards.sicd.io.write",
        "Replaced by functional API. write_chip() becomes write().",
    ),
    "NITFDetails": (
        "sarkit.io.nitf.NITFFile",
        "Header access API changed. Use .file_header instead of .nitf_header.",
    ),
    "NITFReader": (
        "sarkit.io.nitf.read",
        "Functional API replaces class instantiation.",
    ),
    "Serializable": (
        "dataclasses.dataclass",
        "Entire descriptor framework removed. Use @dataclass decorator.",
    ),
    "SICDType": (
        "sarkit.standards.sicd.SICDType",
        "Now a dataclass. .derive() signature changed. "
        ".from_xml_string() becomes sarkit.standards.sicd.from_xml().",
    ),
    "conversion_utility": (
        "sarkit.standards.sicd.io.convert",
        "Simplified API. DEM support moved to separate function.",
    ),
    "check_file": (
        "sarkit.validation.sicd.validate",
        "Returns structured ValidationResult instead of bool.",
    ),
    "SICDTypeReader": (
        "sarkit.io.base.ComplexReader",
        "Subclassing interface changed. get_sicds_as_tuple() removed.",
    ),
}


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------

@dataclass
class MigrationFinding:
    """A single migration finding tied to a specific file location."""
    file_path: str
    line_number: int
    sarpy_module: str
    imported_names: List[str]
    sarkit_equivalent: str
    risk: str
    guidance: str
    code_snippet: str = ""


@dataclass
class BreakingChange:
    """A usage of a function/class with a known breaking API change."""
    file_path: str
    line_number: int
    symbol: str
    sarkit_replacement: str
    change_description: str
    code_snippet: str = ""


@dataclass
class MigrationReport:
    """Complete migration assessment for a scanned codebase."""
    scan_timestamp: str
    scanned_path: str
    total_files_scanned: int
    files_with_sarpy_usage: int
    findings: List[MigrationFinding] = field(default_factory=list)
    breaking_changes: List[BreakingChange] = field(default_factory=list)
    summary: Dict[str, int] = field(default_factory=dict)

    @property
    def critical_count(self) -> int:
        return sum(1 for f in self.findings if f.risk == "CRITICAL")

    @property
    def high_count(self) -> int:
        return sum(1 for f in self.findings if f.risk == "HIGH")

    @property
    def medium_count(self) -> int:
        return sum(1 for f in self.findings if f.risk == "MEDIUM")

    @property
    def low_count(self) -> int:
        return sum(1 for f in self.findings if f.risk == "LOW")

    @property
    def estimated_effort_hours(self) -> float:
        """Rough effort estimate based on risk-weighted findings."""
        weights = {"CRITICAL": 8.0, "HIGH": 4.0, "MEDIUM": 2.0, "LOW": 0.5}
        return sum(weights.get(f.risk, 1.0) for f in self.findings)

    def to_json(self, indent: int = 2) -> str:
        """Export report as JSON for project-tracking tool ingestion."""
        data = asdict(self)
        data["critical_count"] = self.critical_count
        data["high_count"] = self.high_count
        data["medium_count"] = self.medium_count
        data["low_count"] = self.low_count
        data["estimated_effort_hours"] = self.estimated_effort_hours
        data["total_findings"] = len(self.findings)
        data["total_breaking_changes"] = len(self.breaking_changes)
        return json.dumps(data, indent=indent, default=str)

    def print_summary(self) -> None:
        """Print a human-readable migration summary to stdout."""
        print("=" * 72)
        print("  SarPy -> SARKit Migration Assessment Report")
        print("=" * 72)
        print(f"  Scanned:   {self.scanned_path}")
        print(f"  Timestamp: {self.scan_timestamp}")
        print(f"  Files scanned:       {self.total_files_scanned}")
        print(f"  Files with SarPy:    {self.files_with_sarpy_usage}")
        print("-" * 72)
        print(f"  CRITICAL findings:   {self.critical_count}")
        print(f"  HIGH findings:       {self.high_count}")
        print(f"  MEDIUM findings:     {self.medium_count}")
        print(f"  LOW findings:        {self.low_count}")
        print(f"  Breaking API changes:{len(self.breaking_changes):>4}")
        print("-" * 72)
        print(f"  Estimated effort:    {self.estimated_effort_hours:.1f} hours")
        print("=" * 72)

        if self.findings:
            print("\n  Migration Findings (by risk):")
            print("-" * 72)
            for risk_level in ["CRITICAL", "HIGH", "MEDIUM", "LOW"]:
                items = [f for f in self.findings if f.risk == risk_level]
                if not items:
                    continue
                print(f"\n  [{risk_level}]")
                for item in items:
                    print(f"    {item.file_path}:{item.line_number}")
                    print(f"      sarpy:  {item.sarpy_module}")
                    names_str = ", ".join(item.imported_names) if item.imported_names else "(module)"
                    print(f"      names:  {names_str}")
                    print(f"      sarkit: {item.sarkit_equivalent}")
                    print(f"      note:   {item.guidance}")
                    print()

        if self.breaking_changes:
            print("\n  Breaking API Changes:")
            print("-" * 72)
            for bc in self.breaking_changes:
                print(f"    {bc.file_path}:{bc.line_number}")
                print(f"      symbol:      {bc.symbol}")
                print(f"      replacement: {bc.sarkit_replacement}")
                print(f"      change:      {bc.change_description}")
                print()

        # Per-module summary
        module_counts: Dict[str, int] = {}
        for f in self.findings:
            module_counts[f.sarpy_module] = module_counts.get(f.sarpy_module, 0) + 1
        if module_counts:
            print("\n  Module Usage Frequency:")
            print("-" * 72)
            for mod, count in sorted(module_counts.items(), key=lambda x: -x[1]):
                print(f"    {count:>4}x  {mod}")
            print()


# ---------------------------------------------------------------------------
# AST-based scanner
# ---------------------------------------------------------------------------

class SarPyImportVisitor(ast.NodeVisitor):
    """AST visitor that collects all sarpy import statements and usages."""

    def __init__(self, file_path: str, source_lines: List[str]):
        self.file_path = file_path
        self.source_lines = source_lines
        self.findings: List[MigrationFinding] = []
        self.breaking_changes: List[BreakingChange] = []
        # Track imported names for breaking-change detection
        self._imported_symbols: Dict[str, Tuple[str, int]] = {}

    def visit_Import(self, node: ast.Import) -> None:
        for alias in node.names:
            if alias.name.startswith("sarpy"):
                self._record_import(
                    node.lineno,
                    alias.name,
                    [],
                )
        self.generic_visit(node)

    def visit_ImportFrom(self, node: ast.ImportFrom) -> None:
        if node.module and node.module.startswith("sarpy"):
            names = [alias.name for alias in (node.names or [])]
            self._record_import(node.lineno, node.module, names)
            # Track symbol-level imports for breaking-change detection
            for name in names:
                local_name = name
                for alias in node.names:
                    if alias.name == name and alias.asname:
                        local_name = alias.asname
                self._imported_symbols[local_name] = (name, node.lineno)
        self.generic_visit(node)

    def visit_Name(self, node: ast.Name) -> None:
        if node.id in self._imported_symbols:
            original_name, _import_line = self._imported_symbols[node.id]
            if original_name in BREAKING_API_CHANGES:
                replacement, description = BREAKING_API_CHANGES[original_name]
                snippet = self._get_snippet(node.lineno)
                self.breaking_changes.append(BreakingChange(
                    file_path=self.file_path,
                    line_number=node.lineno,
                    symbol=original_name,
                    sarkit_replacement=replacement,
                    change_description=description,
                    code_snippet=snippet,
                ))
        self.generic_visit(node)

    def visit_Attribute(self, node: ast.Attribute) -> None:
        if node.attr in BREAKING_API_CHANGES:
            # Check if we can resolve the full chain to a sarpy module
            full_name = self._resolve_attribute_chain(node)
            if full_name and "sarpy" in full_name:
                replacement, description = BREAKING_API_CHANGES[node.attr]
                snippet = self._get_snippet(node.lineno)
                self.breaking_changes.append(BreakingChange(
                    file_path=self.file_path,
                    line_number=node.lineno,
                    symbol=node.attr,
                    sarkit_replacement=replacement,
                    change_description=description,
                    code_snippet=snippet,
                ))
        self.generic_visit(node)

    def _resolve_attribute_chain(self, node: ast.Attribute) -> Optional[str]:
        parts = [node.attr]
        current = node.value
        while isinstance(current, ast.Attribute):
            parts.append(current.attr)
            current = current.value
        if isinstance(current, ast.Name):
            parts.append(current.id)
        parts.reverse()
        return ".".join(parts)

    def _record_import(
        self,
        lineno: int,
        module: str,
        names: List[str],
    ) -> None:
        snippet = self._get_snippet(lineno)

        # Find the best matching key in the migration map
        sarkit_module, risk, guidance = self._lookup_migration(module)

        self.findings.append(MigrationFinding(
            file_path=self.file_path,
            line_number=lineno,
            sarpy_module=module,
            imported_names=names,
            sarkit_equivalent=sarkit_module,
            risk=risk.value,
            guidance=guidance,
            code_snippet=snippet,
        ))

        # Check each imported name for breaking changes
        for name in names:
            if name in BREAKING_API_CHANGES:
                replacement, description = BREAKING_API_CHANGES[name]
                self.breaking_changes.append(BreakingChange(
                    file_path=self.file_path,
                    line_number=lineno,
                    symbol=name,
                    sarkit_replacement=replacement,
                    change_description=description,
                    code_snippet=snippet,
                ))

    def _lookup_migration(
        self, module: str
    ) -> Tuple[str, MigrationRisk, str]:
        """Find the best matching migration entry for a sarpy module path."""
        # Try exact match first, then progressively shorter prefixes
        parts = module.split(".")
        for i in range(len(parts), 0, -1):
            prefix = ".".join(parts[:i])
            if prefix in SARPY_TO_SARKIT_MAP:
                return SARPY_TO_SARKIT_MAP[prefix]

        # Fallback for unmapped modules
        return (
            "sarkit (no direct mapping found)",
            MigrationRisk.MEDIUM,
            "No direct SARKit mapping identified for this module. "
            "Manual review required.",
        )

    def _get_snippet(self, lineno: int) -> str:
        if 0 < lineno <= len(self.source_lines):
            return self.source_lines[lineno - 1].rstrip()
        return ""


# ---------------------------------------------------------------------------
# Scanner
# ---------------------------------------------------------------------------

def scan_file(file_path: str) -> Tuple[List[MigrationFinding], List[BreakingChange]]:
    """
    Scan a single Python file for SarPy usage.

    Parameters
    ----------
    file_path : str
        Path to a .py file.

    Returns
    -------
    tuple
        (findings, breaking_changes)
    """
    try:
        with open(file_path, "r", encoding="utf-8", errors="replace") as fh:
            source = fh.read()
    except (OSError, IOError):
        return [], []

    try:
        tree = ast.parse(source, filename=file_path)
    except SyntaxError:
        return [], []

    source_lines = source.splitlines()
    visitor = SarPyImportVisitor(file_path, source_lines)
    visitor.visit(tree)
    return visitor.findings, visitor.breaking_changes


def scan_directory(
    root_path: str,
    extensions: Optional[List[str]] = None,
    exclude_dirs: Optional[List[str]] = None,
) -> MigrationReport:
    """
    Recursively scan a directory for SarPy usage.

    Parameters
    ----------
    root_path : str
        Root directory to scan.
    extensions : list, optional
        File extensions to scan.  Defaults to ['.py'].
    exclude_dirs : list, optional
        Directory names to skip.  Defaults to common non-source dirs.

    Returns
    -------
    MigrationReport
    """
    if extensions is None:
        extensions = [".py"]
    if exclude_dirs is None:
        exclude_dirs = [
            "__pycache__", ".git", ".tox", ".eggs", "node_modules",
            ".venv", "venv", "env", ".mypy_cache", ".pytest_cache",
            "build", "dist",
        ]

    all_findings: List[MigrationFinding] = []
    all_breaking: List[BreakingChange] = []
    total_files = 0
    files_with_usage = 0

    for dirpath, dirnames, filenames in os.walk(root_path):
        # Prune excluded directories
        dirnames[:] = [d for d in dirnames if d not in exclude_dirs]

        for fname in filenames:
            if not any(fname.endswith(ext) for ext in extensions):
                continue
            total_files += 1
            fpath = os.path.join(dirpath, fname)
            findings, breaking = scan_file(fpath)
            if findings or breaking:
                files_with_usage += 1
                all_findings.extend(findings)
                all_breaking.extend(breaking)

    # Deduplicate breaking changes (same symbol at same location)
    seen_breaking = set()
    unique_breaking = []
    for bc in all_breaking:
        key = (bc.file_path, bc.line_number, bc.symbol)
        if key not in seen_breaking:
            seen_breaking.add(key)
            unique_breaking.append(bc)

    report = MigrationReport(
        scan_timestamp=datetime.datetime.now(datetime.timezone.utc).isoformat(),
        scanned_path=str(root_path),
        total_files_scanned=total_files,
        files_with_sarpy_usage=files_with_usage,
        findings=all_findings,
        breaking_changes=unique_breaking,
    )

    # Build module summary
    module_counts: Dict[str, int] = {}
    for f in all_findings:
        module_counts[f.sarpy_module] = module_counts.get(f.sarpy_module, 0) + 1
    report.summary = module_counts

    return report


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main(args=None):
    parser = argparse.ArgumentParser(
        prog="sarpy-migration-scanner",
        description=(
            "Scan a Python codebase for SarPy API usage and generate a "
            "prioritized migration plan for transitioning to NGA SARKit."
        ),
    )
    parser.add_argument(
        "path",
        help="Path to the directory or file to scan.",
    )
    parser.add_argument(
        "--json",
        dest="json_output",
        metavar="FILE",
        help="Write JSON report to FILE.",
    )
    parser.add_argument(
        "--exclude-dir",
        dest="exclude_dirs",
        action="append",
        default=None,
        help="Additional directory names to exclude (repeatable).",
    )
    parser.add_argument(
        "--quiet",
        action="store_true",
        help="Suppress human-readable output; only write JSON.",
    )

    config = parser.parse_args(args)
    target = config.path

    if os.path.isfile(target):
        findings, breaking = scan_file(target)
        report = MigrationReport(
            scan_timestamp=datetime.datetime.now(
                datetime.timezone.utc
            ).isoformat(),
            scanned_path=target,
            total_files_scanned=1,
            files_with_sarpy_usage=1 if findings else 0,
            findings=findings,
            breaking_changes=breaking,
        )
    elif os.path.isdir(target):
        report = scan_directory(
            target,
            exclude_dirs=config.exclude_dirs,
        )
    else:
        print(f"Error: {target} is not a valid file or directory.", file=sys.stderr)
        return 1

    if not config.quiet:
        report.print_summary()

    if config.json_output:
        json_str = report.to_json()
        with open(config.json_output, "w") as fh:
            fh.write(json_str)
        if not config.quiet:
            print(f"\n  JSON report written to: {config.json_output}")

    return 0 if report.critical_count == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
