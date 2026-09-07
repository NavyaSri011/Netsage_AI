"""NetSage AI - Phase 5 validation for the Rule Checker.

A standalone, dependency-light test runner (does NOT require pytest).
Run with the project Python 3.12 interpreter:

    py -3.12 tests/test_rule_checker.py

It verifies each deterministic rule across representative inputs, plus
the "clean config" negative case and the explicit rules filter.
"""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

from src.rule_checker import (
    RULE_NAMES,
    check,
    SAMPLE_ADMIN_DOWN,
    SAMPLE_BAD_GATEWAY,
    SAMPLE_DUPLICATE_IP,
    SAMPLE_SUBNET_MISMATCH,
    CLEAN_CONFIG,
)


def has_rule(results, rule):
    return any(r["rule"] == rule for r in results)


def run():
    results = []

    def record(name, ok, detail=""):
        results.append((name, ok, detail))
        status = "PASS" if ok else "FAIL"
        print("[%s] %s  %s" % (status, name, detail))

    # 1. Duplicate IP detection
    print("\n--- Duplicate IP ---")
    r = check(SAMPLE_DUPLICATE_IP)
    record("detects duplicate_ip", has_rule(r, "duplicate_ip"))
    record("duplicate finding is high severity", any(
        f["severity"] == "high" for f in r if f["rule"] == "duplicate_ip"))

    # 2. Default gateway validation
    print("\n--- Default Gateway ---")
    r = check(SAMPLE_BAD_GATEWAY)
    record("detects bad gateway", has_rule(r, "default_gateway"))
    gws = [f for f in r if f["rule"] == "default_gateway"]
    record("gateway finding cites configured vs router IPs", any(
        "192.168.10.99" in f["message"] and "192.168.10.1" in f["message"] for f in gws))

    # 3. Interface status check
    print("\n--- Interface Status ---")
    r = check(SAMPLE_ADMIN_DOWN)
    record("detects administratively down", has_rule(r, "interface_status"))
    status_f = [f for f in r if f["rule"] == "interface_status"]
    record("admin-down is critical severity", any(
        f["severity"] == "critical" for f in status_f))

    # 4. Subnet mask mismatch
    print("\n--- Subnet Mismatch ---")
    r = check(SAMPLE_SUBNET_MISMATCH)
    record("detects subnet_mismatch", has_rule(r, "subnet_mismatch"))

    # 5. Clean config -> no findings
    print("\n--- Clean Config (negative) ---")
    r = check(CLEAN_CONFIG)
    record("clean config yields no findings", len(r) == 0, "got %d" % len(r))

    # 6. Rule filter selects only requested rules
    print("\n--- Rule Filter ---")
    r = check(SAMPLE_ADMIN_DOWN, rules=["duplicate_ip"])
    record("only requested rules run", all(f["rule"] == "duplicate_ip" for f in r))

    # 7. Interface up/down (duplex mismatch) detection
    print("\n--- Interface up/down ---")
    r = check({"interfaces": [
        {"name": "Fa0/1", "status": "up/down", "duplex": "half"},
    ]})
    record("detects up/down with duplex hint", has_rule(r, "interface_status"))
    dup = [f for f in r if f["rule"] == "interface_status"]
    record("up/down mentions duplex mismatch", any("duplex" in f["message"] for f in dup))

    # 8. Missing gateway detection
    print("\n--- Missing Gateway ---")
    r = check({"hosts": [
        {"name": "PC_A", "ip": "192.168.10.10", "mask": "255.255.255.0", "gateway": ""},
    ]})
    record("detects missing gateway", has_rule(r, "default_gateway"))
    missing = [f for f in r if f["rule"] == "default_gateway"]
    record("missing-gateway finding present", any("empty default" in f["message"] for f in missing))

    # 9. VLAN assignment mismatch detection
    print("\n--- VLAN Assignment ---")
    r = check({
        "vlans": [{"vlan": 10, "name": "LAN10", "subnet": "192.168.10.0/24"}],
        "interfaces": [
            {"name": "Fa0/1", "ip": "192.168.20.1", "mask": "255.255.255.0",
             "vlan": 10, "switchport_mode": "access"},
        ],
    })
    record("detects vlan ip out-of-range", has_rule(r, "vlan_assignment"))

    # 10. Invalid route next-hop detection
    print("\n--- Route Validation ---")
    r = check({"routes": [
        {"destination": "192.168.30.0", "mask": "255.255.255.0", "next_hop": "not-an-ip"},
    ]})
    record("detects invalid route next-hop", has_rule(r, "route_validation"))

    # Summary
    passed = sum(1 for _, ok, _ in results if ok)
    total = len(results)
    print("\n=========================================")
    print("RULE CHECKER RESULT: %d/%d checks PASSED" % (passed, total))
    print("=========================================")
    return 0 if passed == total else 1


if __name__ == "__main__":
    sys.exit(run())
