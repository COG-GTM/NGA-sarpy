"""
Command-line entry point for cross-domain transfer validation.

Usage::

    python -m sarpy.security --source SIPRNET --target JWICS /path/to/file.nitf
"""

__classification__ = "UNCLASSIFIED"

from sarpy.security.cross_domain_validation import main

if __name__ == '__main__':
    main()
