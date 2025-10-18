#!/usr/bin/env python3
"""Test that zones without nameserver raise an error"""

import sys
import tempfile
import subprocess
from pathlib import Path


def test_no_nameserver():
    """Test that a zone without nameserver raises a clear error"""
    toml_content = """[defaults]
email = "admin@example.com"

[[zone]]
name = "test.local"

[zone.hosts]
host1 = ["192.168.1.10"]
"""

    with tempfile.NamedTemporaryFile(mode="w", suffix=".toml", delete=False) as f:
        f.write(toml_content)
        toml_file = f.name

    try:
        result = subprocess.run(
            [sys.executable, "zonefile.py", "-i", toml_file], capture_output=True, text=True, cwd=Path(__file__).parent
        )

        # Should fail with non-zero exit code
        if result.returncode == 0:
            print("❌ FAILED: Expected error but script succeeded")
            return False

        # Check for meaningful error message
        if "nameserver: value is missing" in result.stderr.lower():
            print("✅ Correct error: Zone without nameserver is rejected")
            print(f"   Error message: {result.stderr.strip()}")
            return True
        else:
            print("❌ FAILED: Wrong error message")
            print(f"   Expected: 'no nameserver defined'")
            print(f"   Got: {result.stderr}")
            return False

    finally:
        Path(toml_file).unlink(missing_ok=True)


if __name__ == "__main__":
    print("Testing nameserver validation")
    print("=" * 60)

    if test_no_nameserver():
        print("\n✅ TEST PASSED")
        sys.exit(0)
    else:
        print("\n❌ TEST FAILED")
        sys.exit(1)
