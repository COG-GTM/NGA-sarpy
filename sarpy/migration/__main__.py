"""
Command-line entry point for the SarPy-to-SARKit migration scanner.

Usage::

    python -m sarpy.migration /path/to/project
    python -m sarpy.migration /path/to/project --json report.json
"""

__classification__ = "UNCLASSIFIED"

from sarpy.migration.sarkit_scanner import main

if __name__ == '__main__':
    main()
