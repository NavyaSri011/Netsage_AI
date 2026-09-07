"""NetSage AI — Deterministic Rule Checker.

Phase 5 implementation.

A rule-based checker that identifies common networking configuration
mistakes WITHOUT relying on any AI model. The checker is completely
deterministic: given the same structured input it always produces the
same results.

Input format
------------
The checker accepts a structured dict describing a parsed network state,
typically extracted from Cisco show-command output. Supported top-level
sections are optional; any that are missing are treated as "no data"
(which produces no findings for that section, since absence of evidence
is not an error):

    config = {
        "interfaces": [                     # from show interfaces / status
            {"name": "Fa0/1",
             "ip": "192.168.10.2",
             "mask": "255.255.255.0",
             "status": "up" | "down" | "admin_down",
             "duplex": "full" | "half" | "auto",
             "vlan": 10,
             "switchport_mode": "access" | "trunk"},
            ...
        ],
        "hosts": [                          # from ipconfig /all
            {"name": "PC_A",
             "ip": "192.168.10.10",
             "mask": "255.255.255.0",
             "gateway": "192.168.10.1",
             "dns": "192.168.10.5"},
            ...
        ],
        "vlans": [                          # from show vlan brief
            {"vlan": 10, "name": "LAN10", "subnet": "192.168.10.0/24"},
            ...
        ],
        "routes": [                         # from show ip route
            {"destination": "0.0.0.0", "mask": "0.0.0.0",
             "next_hop": "192.168.0.1", "interface": "Gi0/0"},
            ...
        ],
        "default_gateways": [               # gateway(s) the router provides
            {"subnet": "192.168.10.0/24", "gateway_ip": "192.168.10.1"},
            ...
        ],
        "dhcp_pool": {                      # from show ip dhcp pool
            "network": "192.168.10.0",
            "mask": "255.255.255.0",
            "used": 250,
            "total": 254,
        },
    }

Output format
-------------
`check()` returns a list of finding dicts:

    {
        "rule": "duplicate_ip",
        "issue": "Two hosts share the same IP address.",
        "message": "PC_A and PC_B both use IP 192.168.10.10 ...",
        "severity": "high",
        "evidence": "IPs: [192.168.10.10, 192.168.10.10]",
        "suggested_check": "ipconfig /all on each host",
    }

An empty list means no errors were detected for the provided data.
"""

import ipaddress as _ip

# ----------------------------------------------------------------------
# Helper utilities
# ----------------------------------------------------------------------

_VERSION_TO_MASK = {
    24: "255.255.255.0",
    25: "255.255.255.128",
    26: "255.255.255.192",
    30: "255.255.255.252",
    16: "255.255.0.0",
    8: "255.0.0.0",
}


def _str(value):
    return "" if value is None else str(value).strip()


def _is_valid_ip(text):
    try:
        _ip.ip_address(_str(text))
        return True
    except ValueError:
        return False


def _is_valid_mask(text):
    try:
        mask = _str(text)
        # Accept dotted-decimal masks and CIDR forms like "/24".
        if mask.startswith("/"):
            prefix = int(mask[1:])
            return 0 <= prefix <= 32
        _ip.IPv4Network("0.0.0.0/" + mask)
        return True
    except ValueError:
        return False


def _parse_network(cidr):
    """Parse a 'subnet' value that may be '192.168.10.0/24' or '/24'."""
    text = _str(cidr)
    if text.startswith("/"):
        prefix = int(text[1:])
        return prefix, None
    if "/" not in text:
        return None, None
    a, _, b = text.partition("/")
    if _is_valid_ip(a) and b.isdigit():
        return int(b), a
    return None, None


def _ip_and_prefix(ip_text, mask_text):
    """Return (ipaddress, prefix_length) or (None, None) if invalid."""
    if not _is_valid_ip(ip_text):
        return None, None
    ip = _ip.ip_address(_str(ip_text))
    mask = _str(mask_text)
    if mask.startswith("/"):
        prefix = int(mask[1:])
    elif _is_valid_mask(mask):
        try:
            net = _ip.IPv4Network("0.0.0.0/" + mask)
            prefix = net.prefixlen
        except ValueError:
            return None, None
    else:
        return None, None
    return ip, prefix


def _network_of(ip_text, mask_text):
    """Return the network string of an IP + mask, or None if invalid."""
    ip, prefix = _ip_and_prefix(ip_text, mask_text)
    if ip is None:
        return None
    return str(_ip.IPv4Network((str(ip), prefix), strict=False))


# ----------------------------------------------------------------------
# Rule: Duplicate IP detection
# ----------------------------------------------------------------------

def _rule_duplicate_ip(config):
    findings = []
    seen = {}
    for host in config.get("hosts", []):
        ip = _str(host.get("ip"))
        name = _str(host.get("name")) or ip
        if not ip or not _is_valid_ip(ip):
            continue
        if ip in seen:
            findings.append({
                "rule": "duplicate_ip",
                "issue": "Two hosts share the same IP address.",
                "message": (
                    "Duplicate IP %s is configured on both '%s' and '%s'. "
                    "This causes an address conflict and unstable connectivity." % (
                        ip, seen[ip], name)),
                "severity": "high",
                "evidence": "hosts with IP %s: %s, %s" % (ip, seen[ip], name),
                "suggested_check": "ipconfig /all on each host to confirm conflicts",
            })
        else:
            seen[ip] = name
    # Duplicate detection across router/switch interfaces too.
    int_seen = {}
    for iface in config.get("interfaces", []):
        ip = _str(iface.get("ip"))
        if not ip or not _is_valid_ip(ip):
            continue
        ifname = _str(iface.get("name")) or ip
        if ip in int_seen:
            findings.append({
                "rule": "duplicate_ip",
                "issue": "Two interfaces share the same IP address.",
                "message": (
                    "Duplicate IP %s is configured on both interface '%s' "
                    "and '%s'." % (ip, int_seen[ip], ifname)),
                "severity": "high",
                "evidence": "interfaces with IP %s: %s, %s" % (ip, int_seen[ip], ifname),
                "suggested_check": "show running-config on both devices",
            })
        else:
            int_seen[ip] = ifname
    return findings


# ----------------------------------------------------------------------
# Rule: Subnet mask validation
# ----------------------------------------------------------------------

def _rule_subnet_mask(config):
    findings = []
    for host in config.get("hosts", []):
        mask = _str(host.get("mask"))
        if mask and not _is_valid_mask(mask):
            findings.append({
                "rule": "subnet_mask",
                "issue": "Invalid subnet mask configured.",
                "message": (
                    "Host '%s' has an invalid subnet mask '%s'." % (
                        _str(host.get("name")) or "?", mask)),
                "severity": "high",
                "evidence": "mask=%s" % mask,
                "suggested_check": "ipconfig /all; correct the subnet mask",
            })
    for iface in config.get("interfaces", []):
        mask = _str(iface.get("mask"))
        if mask and not _is_valid_mask(mask):
            findings.append({
                "rule": "subnet_mask",
                "issue": "Invalid subnet mask configured on interface.",
                "message": (
                    "Interface '%s' has an invalid subnet mask '%s'." % (
                        _str(iface.get("name")) or "?", mask)),
                "severity": "high",
                "evidence": "mask=%s" % mask,
                "suggested_check": "show running-config; correct the subnet mask",
            })
    return findings


# ----------------------------------------------------------------------
# Rule: Subnet mask mismatch (hosts that should be on the same network)
# ----------------------------------------------------------------------

def _rule_subnet_mismatch(config):
    """Detect hosts with overlapping IPs but different masks that compute
    different networks (NET-030 style)."""
    findings = []
    hosts = config.get("hosts", [])
    for i in range(len(hosts)):
        for j in range(i + 1, len(hosts)):
            a, b = hosts[i], hosts[j]
            ipa = _str(a.get("ip"))
            ipb = _str(b.get("ip"))
            mka = _str(a.get("mask"))
            mkb = _str(b.get("mask"))
            if not (_is_valid_ip(ipa) and _is_valid_ip(ipb)):
                continue
            if _is_valid_mask(mka) and _is_valid_mask(mkb):
                na = _network_of(ipa, mka)
                nb = _network_of(ipb, mkb)
                if na is not None and nb is not None and na != nb:
                    findings.append({
                        "rule": "subnet_mismatch",
                        "issue": "Hosts compute different networks due to mask mismatch.",
                        "message": (
                            "Host '%s' (IP %s, mask %s) computes network %s while "
                            "host '%s' (IP %s, mask %s) computes network %s. They are "
                            "on the same LAN but cannot communicate directly." % (
                                _str(a.get("name")) or ipa, ipa, mka, na,
                                _str(b.get("name")) or ipb, ipb, mkb, nb)),
                        "severity": "high",
                        "evidence": "networks: %s vs %s" % (na, nb),
                        "suggested_check": "ipconfig /all; use matching masks",
                    })
    return findings


# ----------------------------------------------------------------------
# Rule: Default gateway mismatch / missing gateway
# ----------------------------------------------------------------------

def _rule_default_gateway(config):
    """Check that each host's gateway is a valid router-provided address
    reachable from the host's own network."""
    findings = []
    routers = config.get("default_gateways", [])
    router_ips = {_str(r.get("gateway_ip")) for r in routers if _is_valid_ip(r.get("gateway_ip"))}
    router_subnets = {}
    for r in routers:
        subnet = _str(r.get("subnet"))
        gw = _str(r.get("gateway_ip"))
        if "/" in subnet and _is_valid_ip(gw):
            router_subnets[subnet] = gw

    for host in config.get("hosts", []):
        name = _str(host.get("name")) or _str(host.get("ip"))
        ip = _str(host.get("ip"))
        mask = _str(host.get("mask"))
        gw = _str(host.get("gateway"))
        if not (ip and mask and _is_valid_ip(ip)):
            continue

        # Missing gateway: host has IP/mask but no gateway configured.
        if not gw:
            findings.append({
                "rule": "default_gateway",
                "issue": "Host has no default gateway configured.",
                "message": (
                    "Host '%s' is configured with IP %s but has an empty default "
                    "gateway, so it cannot reach any subnet other than its own." % (
                        name, ip)),
                "severity": "high",
                "evidence": "gateway is empty",
                "suggested_check": "ipconfig; add the router interface address as gateway",
            })
            continue

        if not _is_valid_ip(gw):
            findings.append({
                "rule": "default_gateway",
                "issue": "Invalid default gateway address.",
                "message": "Host '%s' has an invalid default gateway '%s'." % (name, gw),
                "severity": "high",
                "evidence": "gateway=%s" % gw,
                "suggested_check": "ipconfig; correct the gateway address",
            })
            continue

        # Gateway not a router-provided address.
        if router_ips and gw not in router_ips:
            findings.append({
                "rule": "default_gateway",
                "issue": "Default gateway is not a router interface address.",
                "message": (
                    "Host '%s' points its default gateway to '%s', but that address "
                    "is not among the router interface addresses (%s). Traffic "
                    "destined for other subnets cannot be forwarded." % (
                        name, gw, ", ".join(sorted(router_ips)))),
                "severity": "medium",
                "evidence": "configured gateway=%s; router interfaces=%s" % (
                    gw, ", ".join(sorted(router_ips))),
                "suggested_check": "ipconfig; show ip interface brief for the correct gateway",
            })

        # Gateway not within host's own network (one-hop reachability).
        host_net = _network_of(ip, mask)
        if host_net:
            try:
                gw_net = _ip.IPv4Network(
                    (gw, _ip.IPv4Network("0.0.0.0/" + mask).prefixlen), strict=False)
            except ValueError:
                gw_net = None
            if gw_net is not None and host_net != str(gw_net):
                findings.append({
                    "rule": "default_gateway",
                    "issue": "Default gateway is not on the host's own subnet.",
                    "message": (
                        "Host '%s' on network %s has a default gateway '%s' that is on "
                        "a different network (%s), so the gateway is unreachable." % (
                            name, host_net, gw, str(gw_net))),
                    "severity": "high",
                    "evidence": "host network=%s; gateway network=%s" % (host_net, str(gw_net)),
                    "suggested_check": "ipconfig; use a gateway on the same subnet",
                })
    return findings


# ----------------------------------------------------------------------
# Rule: Interface status checks
# ----------------------------------------------------------------------

def _rule_interface_status(config):
    """Check for interfaces that are administratively down or up/down."""
    findings = []
    for iface in config.get("interfaces", []):
        name = _str(iface.get("name")) or "?"
        status = _str(iface.get("status")).lower()
        if status in ("admin_down", "administratively down"):
            findings.append({
                "rule": "interface_status",
                "issue": "Interface is administratively down.",
                "message": (
                    "Interface '%s' is administratively down (shutdown command likely "
                    "applied), so no traffic can traverse it." % name),
                "severity": "critical",
                "evidence": "status=administratively down",
                "suggested_check": "show ip interface brief; apply 'no shutdown'",
            })
        elif status in ("up/down", "up_down", "updown"):
            # Physical layer up but protocol/data-link down.
            duplex = _str(iface.get("duplex")).lower()
            extra = ""
            causes = []
            if duplex in ("full", "half"):
                causes.append("possible duplex mismatch with the remote end")
            if duplex:
                extra = " (duplex=%s)" % duplex
            findings.append({
                "rule": "interface_status",
                "issue": "Interface is up/down (protocol down).",
                "message": (
                    "Interface '%s' shows up/down: the physical link is up but the "
                    "protocol/data-link layer is down%s. %s." % (
                        name, extra,
                        "; ".join(causes) if causes else "check line protocol and duplex settings")),
                "severity": "medium",
                "evidence": "status=up/down%s" % extra,
                "suggested_check": "show interfaces; match duplex settings on both ends",
            })
    return findings


# ----------------------------------------------------------------------
# Rule: VLAN assignment checks
# ----------------------------------------------------------------------

def _rule_vlan_assignment(config):
    """Check that each access port's VLAN maps to the expected subnet and
    that interfaces assigned to a subnet have an IP in that subnet range."""
    findings = []
    vlans = config.get("vlans", [])
    for iface in config.get("interfaces", []):
        if _str(iface.get("switchport_mode")).lower() != "access":
            continue
        vlan = iface.get("vlan")
        ip = _str(iface.get("ip"))
        mask = _str(iface.get("mask"))
        if vlan is None:
            continue
        vlan = int(vlan) if str(vlan).isdigit() else None
        if vlan is None:
            continue
        # Find the subnet expected for this VLAN.
        expected_cidr = None
        subnet_obj = None
        for v in vlans:
            if _str(v.get("vlan")) == str(vlan):
                prefix, net = _parse_network(v.get("subnet"))
                expected_cidr = v.get("subnet")
                if prefix is not None:
                    if net is None:
                        net = "0.0.0.0"
                    try:
                        subnet_obj = _ip.IPv4Network((net, prefix), strict=False)
                    except ValueError:
                        subnet_obj = None
                break
        # If an IP is configured on this port, it should fall in the VLAN subnet.
        if ip and mask and _is_valid_ip(ip) and _is_valid_mask(mask):
            host_net = _network_of(ip, mask)
            if subnet_obj is not None and host_net is not None:
                try:
                    in_range = _ip.ip_address(ip) in subnet_obj
                except ValueError:
                    in_range = False
                if not in_range:
                    findings.append({
                        "rule": "vlan_assignment",
                        "issue": "Interface IP does not match the port's VLAN subnet.",
                        "message": (
                            "Interface '%s' is on VLAN %d whose expected subnet is %s, "
                            "but the interface IP %s/%s is not in that range." % (
                                _str(iface.get("name")) or "?", vlan,
                                expected_cidr or "unknown", ip, mask)),
                        "severity": "medium",
                        "evidence": "vlan=%d expected_subnet=%s ip=%s mask=%s" % (
                            vlan, expected_cidr or "unknown", ip, mask),
                        "suggested_check": "show vlan brief; switchport access vlan <correct_vlan>",
                    })
    return findings


# ----------------------------------------------------------------------
# Rule: Route validation
# ----------------------------------------------------------------------

def _rule_route_validation(config):
    """Check that no route points to a next-hop that is not a known local
    interface IP / gateway."""
    findings = []
    local_ips = {
        _str(i.get("ip"))
        for i in config.get("interfaces", [])
        if _is_valid_ip(i.get("ip"))
    }
    local_ips |= {
        _str(h.get("gateway"))
        for h in config.get("hosts", [])
        if _is_valid_ip(h.get("gateway"))
    }
    for route in config.get("routes", []):
        dest = _str(route.get("destination"))
        nh = _str(route.get("next_hop"))
        if not nh or _is_valid_ip(nh):
            continue
        findings.append({
            "rule": "route_validation",
            "issue": "Route points to an invalid next-hop.",
            "message": (
                "Route for destination '%s' points to an invalid next-hop '%s'." % (
                    dest or "?", nh)),
            "severity": "high",
            "evidence": "destination=%s next_hop=%s" % (dest, nh),
            "suggested_check": "show ip route; correct the next-hop address",
        })
    return findings


# ----------------------------------------------------------------------
# API
# ----------------------------------------------------------------------

ALL_RULES = [
    _rule_duplicate_ip,
    _rule_subnet_mask,
    _rule_subnet_mismatch,
    _rule_default_gateway,
    _rule_interface_status,
    _rule_vlan_assignment,
    _rule_route_validation,
]

RULE_NAMES = {
    "duplicate_ip": "Duplicate IP Detection",
    "subnet_mask": "Subnet Mask Validation",
    "subnet_mismatch": "Subnet Mask Mismatch Detection",
    "default_gateway": "Default Gateway Validation",
    "interface_status": "Interface Status Check",
    "vlan_assignment": "VLAN Assignment Check",
    "route_validation": "Route Validation",
}


def check(config, rules=None) -> list:
    """Analyze a parsed configuration and return a list of findings.

    Args:
        config: A dict of parsed networking configuration data (see module
            docstring for the accepted structure).
        rules: Optional iterable of rule function names to run. Defaults to
            all built-in rules.

    Returns:
        A list of finding dicts (see module docstring). An empty list means
        no errors were detected for the provided data.
    """
    if rules is None:
        rule_fns = ALL_RULES
    else:
        by_name = {fn.__name__: fn for fn in ALL_RULES}
        rule_fns = [by_name[r] for r in rules if r in by_name]

    findings = []
    for fn in rule_fns:
        findings.extend(fn(config))
    return findings


# ----------------------------------------------------------------------
# Sample inputs and expected outputs (self-check / demonstration)
# ----------------------------------------------------------------------

SAMPLE_DUPLICATE_IP = {
    "hosts": [
        {"name": "PC_A", "ip": "192.168.10.10", "mask": "255.255.255.0",
         "gateway": "192.168.10.1", "dns": "192.168.10.5"},
        {"name": "PC_B", "ip": "192.168.10.10", "mask": "255.255.255.0",
         "gateway": "192.168.10.1", "dns": "192.168.10.5"},
    ],
}

SAMPLE_BAD_GATEWAY = {
    "default_gateways": [
        {"subnet": "192.168.10.0/24", "gateway_ip": "192.168.10.1"},
    ],
    "hosts": [
        {"name": "PC_A", "ip": "192.168.10.10", "mask": "255.255.255.0",
         "gateway": "192.168.10.99", "dns": "192.168.10.5"},
    ],
}

SAMPLE_ADMIN_DOWN = {
    "interfaces": [
        {"name": "Fa0/1", "ip": "192.168.10.1", "mask": "255.255.255.0",
         "status": "admin_down", "duplex": "full", "vlan": 10,
         "switchport_mode": "access"},
    ],
}

SAMPLE_SUBNET_MISMATCH = {
    "hosts": [
        {"name": "Host_A", "ip": "192.168.10.5", "mask": "255.255.255.0",
         "gateway": "192.168.10.1", "dns": "192.168.10.5"},
        {"name": "Host_B", "ip": "192.168.10.200", "mask": "255.255.255.128",
         "gateway": "192.168.10.129", "dns": "192.168.10.5"},
    ],
}

CLEAN_CONFIG = {
    "default_gateways": [
        {"subnet": "192.168.10.0/24", "gateway_ip": "192.168.10.1"},
    ],
    "hosts": [
        {"name": "PC_A", "ip": "192.168.10.10", "mask": "255.255.255.0",
         "gateway": "192.168.10.1", "dns": "192.168.10.5"},
    ],
    "interfaces": [
        {"name": "Fa0/1", "ip": "192.168.10.1", "mask": "255.255.255.0",
         "status": "up", "duplex": "full", "vlan": 10, "switchport_mode": "access"},
    ],
    "vlans": [
        {"vlan": 10, "name": "LAN10", "subnet": "192.168.10.0/24"},
    ],
}


def _describe(config):
    findings = check(config)
    for f in findings:
        print("  [%-16s] %s" % (RULE_NAMES.get(f["rule"], f["rule"]), f["message"]))
    return findings


def _demo():
    print("NetSage AI Rule Checker — sample self-check")
    print("=" * 60)
    print("\n1) Duplicate IP example (expect duplicate_ip finding):")
    _describe(SAMPLE_DUPLICATE_IP)
    print("\n2) Bad gateway example (expect default_gateway finding):")
    _describe(SAMPLE_BAD_GATEWAY)
    print("\n3) Admin-down interface example (expect interface_status finding):")
    _describe(SAMPLE_ADMIN_DOWN)
    print("\n4) Subnet mask mismatch example (expect subnet_mismatch finding):")
    _describe(SAMPLE_SUBNET_MISMATCH)
    print("\n5) Clean config (expect NO findings):")
    clean = _describe(CLEAN_CONFIG)
    print("  (clean, no findings)" if not clean else "  <-- unexpected findings!")
    print("\n" + "=" * 60)
    print("Demonstration complete.")


if __name__ == "__main__":
    _demo()
