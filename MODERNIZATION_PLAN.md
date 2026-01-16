# SarPy Modernization Plan

This document tracks the modernization efforts for the SarPy repository. Each task is linked to a corresponding Jira issue in the UF project for tracking purposes.

**Jira Epic:** [UF-60](https://cog-gtm.atlassian.net/browse/UF-60) - Modernize SARPy Build System, Testing, and Dependency Management

**Repository:** https://github.com/COG-GTM/NGA-sarpy

**Current Version:** 1.3.62

**Python Support:** 3.8, 3.9, 3.10, 3.11, 3.12

---

## Overview

SarPy is a Python package for SAR (Synthetic Aperture Radar) data processing developed by the National Geospatial-Intelligence Agency (NGA). This modernization effort covers three key areas to improve developer experience, code quality, and maintainability.

### Priority Order

1. **Task 1: Build System Modernization** - Must be completed first as it provides the foundation for Task 3
2. **Task 2: Testing Infrastructure Simplification** - Can be done in parallel with Task 1
3. **Task 3: Dependency Management Modernization** - Depends on Task 1 completion

---

## Task 1: Build System Modernization - Migrate to pyproject.toml

**Jira Issue:** [UF-61](https://cog-gtm.atlassian.net/browse/UF-61)

**Status:** Not Started

### Description

Replace the traditional `setup.py` build configuration with modern `pyproject.toml` standard.

### Current State

The repository currently uses `setup.py` for package configuration:

**File:** `setup.py`

```python
# Current dependencies (lines 65-70)
install_requires=['h5py', 'numpy>=1.19.0', 'pillow', 'scipy', 'matplotlib', 'shapely>=1.6.4', 'lxml>=4.1.1'],
extras_require={
    "all": ['smart_open[http]', 'pytest>=3.3.2', 'networkx>=2.5'],
},
```

**Package metadata** is sourced from `sarpy/__about__.py`:
- Package name: `sarpy`
- Version: `1.3.62`
- License: MIT

**Package data** includes XSD schema files for:
- SICD schemas (`sarpy/io/complex/sicd_schema/`)
- CPHD schemas (`sarpy/io/phase_history/cphd_schema/`)
- CRSD schemas (`sarpy/io/phase_history/crsd_schema/`)
- SIDD schemas (`sarpy/io/product/sidd_schema/`)
- AFRL RDE schemas (`sarpy/annotation/afrl_rde_schema/`)

### Requirements

- [ ] Create a new `pyproject.toml` file in the repository root
- [ ] Migrate all configuration from `setup.py` to `pyproject.toml` including:
  - [ ] Package metadata (name, version, description, authors, license)
  - [ ] Dependencies (h5py, numpy>=1.19.0, pillow, scipy, matplotlib, shapely>=1.6.4, lxml>=4.1.1)
  - [ ] Optional dependencies for extended functionality
  - [ ] Build system declaration
  - [ ] Package data configuration for XSD files
- [ ] Use a modern build backend (setuptools with pyproject.toml or hatchling)
- [ ] Ensure backward compatibility with existing installation methods (`pip install sarpy`)
- [ ] Update installation documentation in `README.md` if needed
- [ ] Verify package builds correctly with `python -m build`
- [ ] Test installation from built wheel

### Benefits

- Declarative configuration
- Better dependency resolution
- Standardized build backend
- Unified tool configuration (can add pytest, black, ruff configs in same file)

### Acceptance Criteria

- [ ] `pyproject.toml` exists and contains all package metadata
- [ ] `pip install .` works correctly
- [ ] `pip install .[all]` installs optional dependencies
- [ ] Package data (XSD files) are included in built distributions
- [ ] CI/CD pipeline passes with new configuration

---

## Task 2: Testing Infrastructure Simplification

**Jira Issue:** [UF-63](https://cog-gtm.atlassian.net/browse/UF-63)

**Status:** Not Started

### Description

Modernize the testing setup to reduce external dependencies and improve consistency.

### Current State

**Testing configuration** (`noxfile.py`):

```python
_PYTHON_VERSIONS = ['3.8', '3.12']
_LOCATIONS = ["tests"]

@nox.session(venv_backend="conda")
@nox.parametrize('version', _PYTHON_VERSIONS)
def test(session, version):
    assert 'SARPY_TEST_PATH' in os.environ  # Required environment variable
    args = session.posargs or _LOCATIONS
    session.conda_install(f'python={version}')
    session.install('.[all]')
    session.run("pytest", *args)
```

**Test file requirements** (from `tests/README.md`):
- Tests require `SARPY_TEST_PATH` environment variable pointing to test data
- Test files are too large to distribute with git
- Comprehensive test files require NGA relationship
- Tests reference paths in JSON structures

**Current test execution methods:**
- `python setup.py test`
- `pytest`
- `nox` (multi-environment testing with conda)

### Requirements

- [ ] Implement containerized testing with Docker for consistent test environments
  - [ ] Create `Dockerfile` for test environment
  - [ ] Create `docker-compose.yml` for test orchestration
  - [ ] Document Docker-based testing workflow
- [ ] Reduce dependency on external test files by implementing mock data generation where possible
  - [ ] Identify tests that can use synthetic/mock data
  - [ ] Create mock data generators for common SAR data structures
  - [ ] Maintain tests requiring real data as optional/integration tests
- [ ] Maintain compatibility with existing nox-based testing workflow
- [ ] Update documentation in `tests/README.md`
- [ ] Ensure tests can run in CI/CD environments without manual setup
  - [ ] Add GitHub Actions workflow for containerized tests
  - [ ] Document CI/CD test configuration

### Benefits

- Consistent test environments across developers and CI
- Reduced external dependencies for basic testing
- Easier onboarding for new contributors
- Reproducible test results

### Acceptance Criteria

- [ ] Docker-based testing works with `docker-compose run tests`
- [ ] Basic unit tests pass without external test data
- [ ] Integration tests clearly documented as requiring external data
- [ ] CI/CD pipeline runs tests in containers
- [ ] `tests/README.md` updated with new testing instructions

---

## Task 3: Dependency Management Modernization

**Jira Issue:** [UF-62](https://cog-gtm.atlassian.net/browse/UF-62)

**Status:** Not Started

**Depends on:** Task 1 (Build System Modernization)

### Description

Implement modern dependency management practices for better security and maintainability.

### Current State

**Core dependencies** (from `setup.py`):
- `h5py` - HDF5 file support (COSMO-SkyMed, ICEYE, NISAR)
- `numpy>=1.19.0` - Array operations
- `pillow` - Image processing (JPEG/JPEG2000, GeoTIFF, KMZ)
- `scipy` - Scientific computing
- `matplotlib` - Plotting
- `shapely>=1.6.4` - Geometric operations
- `lxml>=4.1.1` - XML processing

**Optional dependencies** (from `README.md` and `setup.py`):
- `smart_open[http]` - Remote file access
- `pytest>=3.3.2` - Testing
- `networkx>=2.5` - Graph operations (consistency checks)
- `pyproj` - UTM coordinate support
- `sphinx`, `sphinx_gallery` - Documentation building

### Requirements

- [ ] Implement dependency locking mechanism
  - [ ] Evaluate options: Poetry, Pipenv, pip-tools, or uv
  - [ ] Choose tool that integrates well with pyproject.toml
  - [ ] Generate lock file for reproducible builds
- [ ] Create separate dependency groups:
  - [ ] `core` - Runtime dependencies (h5py, numpy, scipy, matplotlib, shapely, lxml, pillow)
  - [ ] `dev` - Development dependencies (pytest, nox, black, ruff, mypy)
  - [ ] `docs` - Documentation dependencies (sphinx, sphinx_gallery)
  - [ ] `optional` - Optional feature dependencies (smart_open, networkx, pyproj)
  - [ ] `test` - Testing dependencies (pytest, pytest-cov)
- [ ] Set up automated security vulnerability scanning
  - [ ] Add `pip-audit` or `safety` to CI pipeline
  - [ ] Configure Dependabot or Renovate for dependency updates
  - [ ] Document security scanning process
- [ ] Document the new dependency management workflow
  - [ ] Update `README.md` with installation instructions
  - [ ] Create `CONTRIBUTING.md` with development setup guide
- [ ] Ensure compatibility with `pyproject.toml` structure from Task 1

### Benefits

- Better dependency resolution
- Security vulnerability tracking
- Reproducible builds across environments
- Clearer separation of dependency types
- Automated dependency updates

### Acceptance Criteria

- [ ] Lock file exists and is committed to repository
- [ ] `pip install .[dev]` installs development dependencies
- [ ] `pip install .[docs]` installs documentation dependencies
- [ ] Security scanning runs in CI pipeline
- [ ] Dependabot/Renovate configured for automatic updates
- [ ] Documentation updated with new workflow

---

## Progress Tracking

| Task | Jira Issue | Status | Completion Date | PR |
|------|------------|--------|-----------------|-----|
| Build System Modernization | [UF-61](https://cog-gtm.atlassian.net/browse/UF-61) | Not Started | - | - |
| Testing Infrastructure | [UF-63](https://cog-gtm.atlassian.net/browse/UF-63) | Not Started | - | - |
| Dependency Management | [UF-62](https://cog-gtm.atlassian.net/browse/UF-62) | Not Started | - | - |

---

## How to Update This Document

When completing a task:

1. Update the task status in this document
2. Check off completed requirements
3. Add the completion date and PR link to the Progress Tracking table
4. Update the corresponding Jira issue status
5. Commit changes with message: `docs: update modernization plan - [task name] completed`

---

## References

- [PEP 517 - Build system interface](https://peps.python.org/pep-0517/)
- [PEP 518 - pyproject.toml](https://peps.python.org/pep-0518/)
- [PEP 621 - Project metadata in pyproject.toml](https://peps.python.org/pep-0621/)
- [Setuptools pyproject.toml guide](https://setuptools.pypa.io/en/latest/userguide/pyproject_config.html)
- [pip-tools documentation](https://pip-tools.readthedocs.io/)
- [Docker best practices for Python](https://docs.docker.com/language/python/)
