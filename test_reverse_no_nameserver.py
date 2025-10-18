#!/usr/bin/env python3
"""Test that reverse zones without nameserver still work (they use forward zone's NS)"""

import sys
import tempfile
import subprocess
from pathlib import Path


def test_reverse_without_nameserver():
    """Test reverse zone without nameserver - should use forward zone's NS"""
    toml_content = """[defaults]
email = "admin@example.com"
nameserver = ["ns1.test.local."]

[[zone]]
name = "test.local"

[zone.hosts]
ns1 = { ip = ["192.168.1.1"] }
host1 = ["192.168.1.10"]

[reverse]
"192.168.1.0/24" = {}
"""

    with tempfile.NamedTemporaryFile(mode="w", suffix=".toml", delete=False) as f:
        f.write(toml_content)
        toml_file = f.name

    try:
        result = subprocess.run(
            [sys.executable, "zonefile.py", "-i", toml_file, "-f", "nsd", "-o", "/tmp/test_reverse_ns"],
            capture_output=True,
            text=True,
            cwd=Path(__file__).parent,
        )

        if result.returncode != 0:
            print("❌ FAILED: Script failed")
            print(f"STDERR: {result.stderr}")
            return False

        # Check that reverse zone was created
        reverse_zone_file = Path("/tmp/test_reverse_ns/master/1.168.192.in-addr.arpa.zone")
        if not reverse_zone_file.exists():
            print("❌ FAILED: Reverse zone file not created")
            return False

        content = reverse_zone_file.read_text()

        # Should contain NS from forward zone
        if "ns1.test.local." in content:
            print("✅ Reverse zone uses forward zone's nameserver")
            print(f"   Found: ns1.test.local. in reverse zone")
            return True
        else:
            print("❌ FAILED: Nameserver not found in reverse zone")
            print(f"   Content: {content}")
            return False

    finally:
        Path(toml_file).unlink(missing_ok=True)
        import shutil

        shutil.rmtree("/tmp/test_reverse_ns", ignore_errors=True)


def test_no_forward_zone_no_nameserver():
    """Test reverse zone without forward zone and no default nameserver - should fail or use fallback"""
    toml_content = """[defaults]
email = "admin@example.com"

[[zone]]
name = "test.local"

[zone.hosts]
host1 = ["192.168.1.10"]

[reverse]
"192.168.1.0/24" = {}
"""

    with tempfile.NamedTemporaryFile(mode="w", suffix=".toml", delete=False) as f:
        f.write(toml_content)
        toml_file = f.name

    try:
        result = subprocess.run(
            [sys.executable, "zonefile.py", "-i", toml_file, "-f", "nsd", "-o", "/tmp/test_reverse_ns2"],
            capture_output=True,
            text=True,
            cwd=Path(__file__).parent,
        )

        # This should fail because forward zone has no nameserver
        if result.returncode != 0:
            if ".nameserver: value is missing" in result.stderr.lower():
                print("✅ Forward zone without nameserver is rejected (reverse zone not relevant)")
                return True
            else:
                print(f"⚠️  Failed with different error: {result.stderr}")
                return False
        else:
            # If it succeeded, check if fallback NS was used
            reverse_zone_file = Path("/tmp/test_reverse_ns2/master/1.168.192.in-addr.arpa.zone")
            if reverse_zone_file.exists():
                content = reverse_zone_file.read_text()
                if "ns.example.com." in content:
                    print("✅ Uses fallback nameserver (ns.example.com.) for reverse zone")
                    return True
            print("❌ Unexpected success without proper nameserver")
            return False

    finally:
        Path(toml_file).unlink(missing_ok=True)
        import shutil

        shutil.rmtree("/tmp/test_reverse_ns2", ignore_errors=True)


if __name__ == "__main__":
    print("Testing reverse zone nameserver handling")
    print("=" * 60)
    print()

    print("Test 1: Reverse zone with forward zone NS")
    print("-" * 60)
    test1 = test_reverse_without_nameserver()
    print()

    print("Test 2: No forward zone NS, no default NS")
    print("-" * 60)
    test2 = test_no_forward_zone_no_nameserver()
    print()

    if test1 and test2:
        print("=" * 60)
        print("✅ ALL TESTS PASSED")
        sys.exit(0)
    else:
        print("=" * 60)
        print("❌ SOME TESTS FAILED")
        sys.exit(1)
