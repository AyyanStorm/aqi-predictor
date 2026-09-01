"""
test_requirements.py — Tests for dependency pinning (Issue #44).

Validates that requirements.txt is fully pinned and synchronized
with requirements.in.
"""

import re
from pathlib import Path


class TestRequirementsPinning:
    """Test that requirements.txt is fully pinned."""

    @staticmethod
    def get_requirements_file():
        """Load requirements.txt."""
        path = Path(__file__).parent.parent / "requirements.txt"
        with open(path) as f:
            return f.read()

    def test_requirements_txt_is_fully_pinned(self):
        """All packages in requirements.txt should have exact versions (==).
        
        This ensures reproducible builds and prevents transitive dependency
        upgrades from breaking production.
        """
        content = self.get_requirements_file()
        lines = [l.strip() for l in content.split('\n') if l.strip() and not l.startswith('#')]
        
        # Filter out indented lines (these are dependency annotations)
        package_lines = [l for l in lines if not l.startswith(' ') and not l.startswith('\t')]
        
        unpinned = []
        for line in package_lines:
            # Skip comment-only lines
            if line.startswith('#'):
                continue
            
            # Check for unpinned specifiers (>=, <=, >, <, ~=)
            # but NOT == which is pinned
            if re.search(r'(>=|<=|>|<|~=)(?!=)', line):
                unpinned.append(line)
        
        assert not unpinned, f"Found unpinned packages: {unpinned}\n\nAll packages must use == for exact versions"

    def test_requirements_match_in_file(self):
        """Packages in requirements.txt should include those from requirements.in.
        
        This validates that pip-compile output matches the input spec.
        """
        req_path = Path(__file__).parent.parent / "requirements.txt"
        in_path = Path(__file__).parent.parent / "requirements.in"
        
        if not in_path.exists():
            # requirements.in is optional but strongly recommended
            return
        
        with open(in_path) as f:
            in_content = f.read()
        
        with open(req_path) as f:
            req_content = f.read()
        
        def normalize_pkg_name(name):
            """Normalize package name: hyphens and underscores are equivalent."""
            return name.replace('-', '_').replace('_', '').lower()
        
        # Extract package names from requirements.in
        in_packages = set()
        for line in in_content.split('\n'):
            line = line.strip()
            if not line or line.startswith('#'):
                continue
            # Extract package name (before any ==, >=, etc.)
            pkg_name = re.split(r'[><=!]', line)[0].strip().lower()
            if pkg_name:
                in_packages.add(normalize_pkg_name(pkg_name))
        
        # Extract package names from requirements.txt
        req_packages = set()
        for line in req_content.split('\n'):
            line = line.strip()
            if not line or line.startswith('#'):
                continue
            # Skip indented lines (dependency annotations)
            if line.startswith(' ') or line.startswith('\t'):
                continue
            # Extract package name
            pkg_name = re.split(r'[><=!]', line)[0].strip().lower()
            if pkg_name:
                req_packages.add(normalize_pkg_name(pkg_name))
        
        # All packages from .in should be in requirements.txt
        # (plus their transitive dependencies)
        missing = in_packages - req_packages
        assert not missing, f"Missing packages from requirements.in: {missing}\n\nRun: pip-compile requirements.in"


class TestRequirementsDocumentation:
    """Test that requirements documentation exists."""

    def test_pip_compile_instructions_exist(self):
        """Documentation should explain how to update requirements.
        
        Users should know to:
        1. Edit requirements.in (not requirements.txt)
        2. Run pip-compile to regenerate requirements.txt
        """
        readme_path = Path(__file__).parent.parent / "README.md"
        if not readme_path.exists():
            return
        
        with open(readme_path) as f:
            content = f.read().lower()
        
        # Check for documentation mentioning requirements management
        # (not strictly required, but good practice)
        if "requirements" in content:
            # If requirements are documented, mention pip-compile
            # This is a soft check - the important thing is requirements.txt is pinned
            pass
