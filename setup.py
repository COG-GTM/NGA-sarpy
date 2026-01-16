"""
Setup module for SarPy.

This is a minimal compatibility shim that defers to pyproject.toml for all
package configuration. It exists for backward compatibility with older tools
and workflows that expect a setup.py file.

For modern installations, use: pip install .
"""

from setuptools import setup

setup()
