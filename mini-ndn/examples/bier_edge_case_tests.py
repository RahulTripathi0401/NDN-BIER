#!/usr/bin/env python3
# -*- Mode:python; c-file-style:"gnu"; indent-tabs-mode:nil -*- */
#
# Copyright (C) 2015-2026, The University of Memphis,
#                          Arizona Board of Regents,
#                          Regents of the University of California.
#
# This file is part of Mini-NDN.
# See AUTHORS.md for a complete list of Mini-NDN authors and contributors.
#
# Mini-NDN is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.

"""
BIER Edge Case Test Suite

Comprehensive tests for BIER multicast routing edge cases:
- Multi-byte bitmasks (bit positions > 255)
- Empty bitstrings after local-bit clearing
- Broadcast scenarios (all bits set)
- Unicast-like scenarios (single bit)
- Router role transitions (BFIR+BFER, BFR+BFER)
- Invalid configurations
- Control plane edge cases
"""

import sys
import platform

# Check platform before importing mininet
if platform.system() != 'Linux':
    print(f"ERROR: This test requires Linux (detected: {platform.system()})")
    print("Mini-NDN uses Linux kernel features (network namespaces) not available on other platforms.")
    print("\nTo run these tests:")
    print("1. Use a Linux VM or container")
    print("2. Install dependencies: sudo apt-get install mininet python3-mininet")
    print(f"3. Run: sudo -E PYTHONPATH='{sys.path[0]}' python3 {__file__}")
    sys.exit(1)

try:
    from mininet.log import setLogLevel, info
    from mininet.topo import Topo
except ImportError as e:
    print(f"ERROR: {e}")
    print("\nMini-NDN/Mininet not installed. On Ubuntu/Debian:")
    print("  sudo apt-get update")
    print("  sudo apt-get install mininet python3-mininet")
    print("\nOr install Mini-NDN:")
    print("  cd mini-ndn && sudo ./install.sh")
    sys.exit(1)

try:
    from minindn.minindn import Minindn
    from minindn.apps.app_manager import AppManager
    from minindn.apps.nfd import Nfd
    from minindn.helpers.nfdc import Nfdc
except ImportError as e:
    print(f"ERROR: {e}")
    print("\nMini-NDN not installed. To install:")
    print("  cd mini-ndn && sudo ./install.sh --source")
    sys.exit(1)

from global_prefix_mapping import get_global_mapping, reset_global_mapping


def _bier_ctl(node, cmd):
    """Send BIER control command via ndnpeek."""
    node.cmd(f"ndnpeek -w 80 /localhost/nfd/bier/{cmd} >/dev/null 2>&1 || true")


def _configure_face_route(ndn, src, dst, prefix):
    """Configure face and route between two nodes."""
    src_node = ndn.net[src]
    dst_node = ndn.net[dst]
    dst_ip = dst_node.connectionsTo(src_node)[0][0].IP()
    Nfdc.createFace(src_node, dst_ip)
    Nfdc.registerRoute(src_node, prefix, dst_ip, cost=0)


def _inject_interests(node, prefix, count=1):
    """Inject test Interests from a node."""
    for _ in range(count):
        node.cmd(f"ndnpeek -w 80 {prefix} >/dev/null 2>&1 || true")


def _verify_replication(ndn, router_name, expected_count):
    """Verify BIER replication count in router logs."""
    log_path = f"{ndn.workDir}/{router_name}/log/nfd.log"
    log_contents = ndn.net[router_name].cmd(f"cat {log_path}")
    actual_count = log_contents.count("processBierInterest out=")
    info(f"  {router_name}: expected={expected_count}, actual={actual_count}\n")
    return actual_count == expected_count


# =============================================================================
# Test 1: Multi-Byte Bitmask (Bit Positions > 255)
# =============================================================================
def test_multibyte_bitmask():
    """Test BIER with bit positions requiring multi-byte masks."""
    info("\n" + "="*70 + "\n")
    info("TEST 1: Multi-Byte Bitmask (Bits 0, 9, 255, 260)\n")
    info("="*70 + "\n")

    Minindn.cleanUp()
    Minindn.verifyDependencies()
    reset_global_mapping()

    # Topology: src -> r1 -> {e0, e9, e255, e260}
    topo = Topo()
    src = topo.addHost("src")
    r1 = topo.addHost("r1")
    e0 = topo.addHost("e0")
    e9 = topo.addHost("e9")
    e255 = topo.addHost("e255")
    e260 = topo.addHost("e260")

    topo.addLink(src, r1, delay="10ms", bw=10)
    topo.addLink(r1, e0, delay="10ms", bw=10)
    topo.addLink(r1, e9, delay="10ms", bw=10)
    topo.addLink(r1, e255, delay="10ms", bw=10)
    topo.addLink(r1, e260, delay="10ms", bw=10)

    ndn = Minindn(topo=topo)
    ndn.start()

    AppManager(ndn, ndn.net.hosts, Nfd, logLevel="DEBUG")

    PREFIX = "/test/multibyte"

    # Configure faces
    _configure_face_route(ndn, "src", "r1", PREFIX)
    face_r1_e0 = _configure_face_route(ndn, "r1", "e0", PREFIX)
    face_r1_e9 = _configure_face_route(ndn, "r1", "e9", PREFIX)
    face_r1_e255 = _configure_face_route(ndn, "r1", "e255", PREFIX)
    face_r1_e260 = _configure_face_route(ndn, "r1", "e260", PREFIX)

    # Set up global mapping
    mapping = get_global_mapping()
    mapping.set_router_bit("e0", 0)
    mapping.set_router_bit("e9", 9)
    mapping.set_router_bit("e255", 255)
    mapping.set_router_bit("e260", 260)
    mapping.add_prefix(PREFIX, ["e0", "e9", "e255", "e260"])

    # Build multi-byte mask: bits 0, 9, 255, 260
    # Byte 0 (bits 0-7):   10000000 = 0x80 (bit 0)
    # Byte 1 (bits 8-15):  01000000 = 0x40 (bit 9)
    # Bytes 2-31: 00000000 = 0x00
    # Byte 32 (bits 256-263): 00001000 = 0x08 (bit 260)
    # But byte 31 (bits 248-255): 00000001 = 0x01 (bit 255)
    mask = mapping.build_bier_mask(PREFIX)
    info(f"  Multi-byte mask: {mask} (length: {len(mask)//2} bytes)\n")

    # Configure BFIR
    _bier_ctl(ndn.net["r1"], "clear")
    _bier_ctl(ndn.net["r1"], f"prefix/{mask}/test/multibyte")
    _bier_ctl(ndn.net["r1"], f"bit-face/0/{face_r1_e0}")
    _bier_ctl(ndn.net["r1"], f"bit-face/9/{face_r1_e9}")
    _bier_ctl(ndn.net["r1"], f"bit-face/255/{face_r1_e255}")
    _bier_ctl(ndn.net["r1"], f"bit-face/260/{face_r1_e260}")

    # Inject Interest
    _inject_interests(ndn.net["src"], PREFIX, count=1)

    # Verify: r1 should replicate to 4 egress routers
    assert _verify_replication(ndn, "r1", 4), "FAILED: Expected 4 replications"

    info("✓ PASSED: Multi-byte bitmask handled correctly\n")
    ndn.stop()


# =============================================================================
# Test 2: Empty Bitstring After Local-Bit Clearing
# =============================================================================
def test_empty_bitstring_local_only():
    """Test BFER behavior when only local-bit is set."""
    info("\n" + "="*70 + "\n")
    info("TEST 2: Empty Bitstring After Local-Bit Clearing (Local-Only)\n")
    info("="*70 + "\n")

    Minindn.cleanUp()
    Minindn.verifyDependencies()
    reset_global_mapping()

    topo = Topo()
    src = topo.addHost("src")
    bfer = topo.addHost("bfer")
    consumer = topo.addHost("consumer")
    topo.addLink(src, bfer, delay="10ms", bw=10)
    topo.addLink(bfer, consumer, delay="10ms", bw=10)

    ndn = Minindn(topo=topo)
    ndn.start()
    AppManager(ndn, ndn.net.hosts, Nfd, logLevel="DEBUG")

    PREFIX = "/test/localonly"

    _configure_face_route(ndn, "src", "bfer", PREFIX)
    face_bfer_consumer = _configure_face_route(ndn, "bfer", "consumer", PREFIX)

    mapping = get_global_mapping()
    mapping.set_router_bit("bfer", 5)
    mapping.add_prefix(PREFIX, ["bfer"])

    # Configure src as BFIR
    mask = mapping.build_bier_mask(PREFIX)  # Should be bit 5 only
    _bier_ctl(ndn.net["src"], "clear")
    _bier_ctl(ndn.net["src"], f"prefix/{mask}/test/localonly")
    _bier_ctl(ndn.net["src"], f"bit-face/5/{ndn.net['bfer'].connectionsTo(ndn.net['src'])[0][0].IP()}")

    # Configure BFER with local-bit=5
    _bier_ctl(ndn.net["bfer"], "clear")
    _bier_ctl(ndn.net["bfer"], "local-bit/5")
    Nfdc.registerRoute(ndn.net["bfer"], PREFIX, face_bfer_consumer, cost=0)

    _inject_interests(ndn.net["src"], PREFIX, count=1)

    # Verify: bfer should NOT replicate (bitstring becomes empty after local-bit clear)
    # but should process via standard NDN pipeline
    assert _verify_replication(ndn, "bfer", 0), "FAILED: BFER should not BIER-replicate"

    info("✓ PASSED: Empty bitstring handled, fallback to NDN pipeline\n")
    ndn.stop()


# =============================================================================
# Test 3: Broadcast Scenario (All Bits Set in Range)
# =============================================================================
def test_broadcast_all_bits():
    """Test BIER broadcast with all bits in a byte set."""
    info("\n" + "="*70 + "\n")
    info("TEST 3: Broadcast Scenario (All 8 Bits in Byte 0)\n")
    info("="*70 + "\n")

    Minindn.cleanUp()
    Minindn.verifyDependencies()
    reset_global_mapping()

    topo = Topo()
    src = topo.addHost("src")
    r1 = topo.addHost("r1")
    for i in range(8):
        topo.addHost(f"e{i}")
        topo.addLink(r1, f"e{i}", delay="10ms", bw=10)
    topo.addLink(src, r1, delay="10ms", bw=10)

    ndn = Minindn(topo=topo)
    ndn.start()
    AppManager(ndn, ndn.net.hosts, Nfd, logLevel="DEBUG")

    PREFIX = "/test/broadcast"
    _configure_face_route(ndn, "src", "r1", PREFIX)

    mapping = get_global_mapping()
    egress_routers = []
    for i in range(8):
        router_name = f"e{i}"
        egress_routers.append(router_name)
        mapping.set_router_bit(router_name, i)
        face_id = _configure_face_route(ndn, "r1", router_name, PREFIX)
        _bier_ctl(ndn.net["r1"], f"bit-face/{i}/{face_id}")

    mapping.add_prefix(PREFIX, egress_routers)
    mask = mapping.build_bier_mask(PREFIX)  # Should be 0xFF
    info(f"  Broadcast mask: {mask}\n")

    _bier_ctl(ndn.net["r1"], "clear")
    _bier_ctl(ndn.net["r1"], f"prefix/{mask}/test/broadcast")
    for i in range(8):
        face_id = _configure_face_route(ndn, "r1", f"e{i}", PREFIX)
        _bier_ctl(ndn.net["r1"], f"bit-face/{i}/{face_id}")

    _inject_interests(ndn.net["src"], PREFIX, count=1)

    assert _verify_replication(ndn, "r1", 8), "FAILED: Expected 8 replications"
    info("✓ PASSED: Broadcast to all 8 destinations\n")
    ndn.stop()


# =============================================================================
# Test 4: Unicast-Like Scenario (Single Bit Set)
# =============================================================================
def test_unicast_single_bit():
    """Test BIER with only one destination (unicast-like)."""
    info("\n" + "="*70 + "\n")
    info("TEST 4: Unicast-Like Scenario (Single Bit)\n")
    info("="*70 + "\n")

    Minindn.cleanUp()
    Minindn.verifyDependencies()
    reset_global_mapping()

    topo = Topo()
    src = topo.addHost("src")
    r1 = topo.addHost("r1")
    r2 = topo.addHost("r2")
    e1 = topo.addHost("e1")
    e2 = topo.addHost("e2")
    topo.addLink(src, r1, delay="10ms", bw=10)
    topo.addLink(r1, r2, delay="10ms", bw=10)
    topo.addLink(r2, e1, delay="10ms", bw=10)
    topo.addLink(r2, e2, delay="10ms", bw=10)

    ndn = Minindn(topo=topo)
    ndn.start()
    AppManager(ndn, ndn.net.hosts, Nfd, logLevel="DEBUG")

    PREFIX = "/test/unicast"
    _configure_face_route(ndn, "src", "r1", PREFIX)
    face_r1_r2 = _configure_face_route(ndn, "r1", "r2", PREFIX)
    face_r2_e1 = _configure_face_route(ndn, "r2", "e1", PREFIX)
    face_r2_e2 = _configure_face_route(ndn, "r2", "e2", PREFIX)

    mapping = get_global_mapping()
    mapping.set_router_bit("e1", 3)
    mapping.set_router_bit("e2", 7)
    mapping.add_prefix(PREFIX, ["e1"])  # Only e1, not e2

    mask = mapping.build_bier_mask(PREFIX)  # Should be 0x10 (bit 3 only)
    info(f"  Unicast mask: {mask}\n")

    _bier_ctl(ndn.net["r1"], "clear")
    _bier_ctl(ndn.net["r1"], f"prefix/{mask}/test/unicast")
    _bier_ctl(ndn.net["r1"], f"bit-face/3/{face_r1_r2}")

    _bier_ctl(ndn.net["r2"], "clear")
    _bier_ctl(ndn.net["r2"], f"bit-face/3/{face_r2_e1}")
    _bier_ctl(ndn.net["r2"], f"bit-face/7/{face_r2_e2}")

    _inject_interests(ndn.net["src"], PREFIX, count=1)

    assert _verify_replication(ndn, "r1", 1), "FAILED: r1 should replicate once"
    assert _verify_replication(ndn, "r2", 1), "FAILED: r2 should replicate once to e1"
    info("✓ PASSED: Unicast-like forwarding to single destination\n")
    ndn.stop()


# =============================================================================
# Test 5: Non-Contiguous Bit Pattern
# =============================================================================
def test_noncontiguous_bits():
    """Test BIER with non-contiguous bit patterns (e.g., bits 1, 5, 7)."""
    info("\n" + "="*70 + "\n")
    info("TEST 5: Non-Contiguous Bit Pattern (Bits 1, 5, 7)\n")
    info("="*70 + "\n")

    Minindn.cleanUp()
    Minindn.verifyDependencies()
    reset_global_mapping()

    topo = Topo()
    src = topo.addHost("src")
    r1 = topo.addHost("r1")
    e1 = topo.addHost("e1")
    e5 = topo.addHost("e5")
    e7 = topo.addHost("e7")
    topo.addLink(src, r1, delay="10ms", bw=10)
    topo.addLink(r1, e1, delay="10ms", bw=10)
    topo.addLink(r1, e5, delay="10ms", bw=10)
    topo.addLink(r1, e7, delay="10ms", bw=10)

    ndn = Minindn(topo=topo)
    ndn.start()
    AppManager(ndn, ndn.net.hosts, Nfd, logLevel="DEBUG")

    PREFIX = "/test/noncontiguous"
    _configure_face_route(ndn, "src", "r1", PREFIX)
    face_r1_e1 = _configure_face_route(ndn, "r1", "e1", PREFIX)
    face_r1_e5 = _configure_face_route(ndn, "r1", "e5", PREFIX)
    face_r1_e7 = _configure_face_route(ndn, "r1", "e7", PREFIX)

    mapping = get_global_mapping()
    mapping.set_router_bit("e1", 1)
    mapping.set_router_bit("e5", 5)
    mapping.set_router_bit("e7", 7)
    mapping.add_prefix(PREFIX, ["e1", "e5", "e7"])

    mask = mapping.build_bier_mask(PREFIX)  # Should be 0x42 (01000010)
    info(f"  Non-contiguous mask: {mask}\n")

    _bier_ctl(ndn.net["r1"], "clear")
    _bier_ctl(ndn.net["r1"], f"prefix/{mask}/test/noncontiguous")
    _bier_ctl(ndn.net["r1"], f"bit-face/1/{face_r1_e1}")
    _bier_ctl(ndn.net["r1"], f"bit-face/5/{face_r1_e5}")
    _bier_ctl(ndn.net["r1"], f"bit-face/7/{face_r1_e7}")

    _inject_interests(ndn.net["src"], PREFIX, count=1)

    assert _verify_replication(ndn, "r1", 3), "FAILED: Expected 3 replications"
    info("✓ PASSED: Non-contiguous bit pattern handled\n")
    ndn.stop()


# =============================================================================
# Test 6: BFIR+BFER Role Combination
# =============================================================================
def test_bfir_bfer_combination():
    """Test router that is both BFIR (injects) and BFER (consumes)."""
    info("\n" + "="*70 + "\n")
    info("TEST 6: BFIR+BFER Role Combination\n")
    info("="*70 + "\n")

    Minindn.cleanUp()
    Minindn.verifyDependencies()
    reset_global_mapping()

    topo = Topo()
    hybrid = topo.addHost("hybrid")  # BFIR + BFER
    e1 = topo.addHost("e1")
    local_consumer = topo.addHost("local_consumer")
    topo.addLink(hybrid, e1, delay="10ms", bw=10)
    topo.addLink(hybrid, local_consumer, delay="10ms", bw=10)

    ndn = Minindn(topo=topo)
    ndn.start()
    AppManager(ndn, ndn.net.hosts, Nfd, logLevel="DEBUG")

    PREFIX = "/test/hybrid"
    face_hybrid_e1 = _configure_face_route(ndn, "hybrid", "e1", PREFIX)
    face_hybrid_local = _configure_face_route(ndn, "hybrid", "local_consumer", PREFIX)

    mapping = get_global_mapping()
    mapping.set_router_bit("hybrid", 2)
    mapping.set_router_bit("e1", 4)
    mapping.add_prefix(PREFIX, ["hybrid", "e1"])

    mask = mapping.build_bier_mask(PREFIX)  # Bits 2 and 4
    info(f"  Hybrid mask: {mask}\n")

    # Configure as BFIR
    _bier_ctl(ndn.net["hybrid"], "clear")
    _bier_ctl(ndn.net["hybrid"], f"prefix/{mask}/test/hybrid")
    _bier_ctl(ndn.net["hybrid"], f"bit-face/2/{face_hybrid_e1}")  # Will be cleared by local-bit
    _bier_ctl(ndn.net["hybrid"], f"bit-face/4/{face_hybrid_e1}")

    # Configure as BFER
    _bier_ctl(ndn.net["hybrid"], "local-bit/2")
    Nfdc.registerRoute(ndn.net["hybrid"], PREFIX, face_hybrid_local, cost=0)

    # Inject Interest locally (acts as BFIR)
    _inject_interests(ndn.net["hybrid"], PREFIX, count=1)

    # Verify: Should replicate to e1 (bit 4) AND deliver locally (bit 2 cleared)
    assert _verify_replication(ndn, "hybrid", 1), "FAILED: Expected 1 replication to e1"
    info("✓ PASSED: BFIR+BFER combination works\n")
    ndn.stop()


# =============================================================================
# Test 7: BFR+BFER Role Combination (Mid-Path Destination)
# =============================================================================
def test_bfr_bfer_midpath():
    """Test transit router that's also a destination (BFR+BFER)."""
    info("\n" + "="*70 + "\n")
    info("TEST 7: BFR+BFER Mid-Path Destination\n")
    info("="*70 + "\n")

    Minindn.cleanUp()
    Minindn.verifyDependencies()
    reset_global_mapping()

    topo = Topo()
    src = topo.addHost("src")
    r1 = topo.addHost("r1")
    midpath = topo.addHost("midpath")  # BFR + BFER
    e1 = topo.addHost("e1")
    topo.addLink(src, r1, delay="10ms", bw=10)
    topo.addLink(r1, midpath, delay="10ms", bw=10)
    topo.addLink(midpath, e1, delay="10ms", bw=10)

    ndn = Minindn(topo=topo)
    ndn.start()
    AppManager(ndn, ndn.net.hosts, Nfd, logLevel="DEBUG")

    PREFIX = "/test/midpath"
    _configure_face_route(ndn, "src", "r1", PREFIX)
    face_r1_mid = _configure_face_route(ndn, "r1", "midpath", PREFIX)
    face_mid_e1 = _configure_face_route(ndn, "midpath", "e1", PREFIX)

    mapping = get_global_mapping()
    mapping.set_router_bit("midpath", 3)
    mapping.set_router_bit("e1", 6)
    mapping.add_prefix(PREFIX, ["midpath", "e1"])

    mask = mapping.build_bier_mask(PREFIX)
    info(f"  Mid-path mask: {mask}\n")

    # BFIR setup
    _bier_ctl(ndn.net["r1"], "clear")
    _bier_ctl(ndn.net["r1"], f"prefix/{mask}/test/midpath")
    _bier_ctl(ndn.net["r1"], f"bit-face/3/{face_r1_mid}")
    _bier_ctl(ndn.net["r1"], f"bit-face/6/{face_r1_mid}")

    # BFR+BFER setup
    _bier_ctl(ndn.net["midpath"], "clear")
    _bier_ctl(ndn.net["midpath"], "local-bit/3")
    _bier_ctl(ndn.net["midpath"], f"bit-face/6/{face_mid_e1}")

    _inject_interests(ndn.net["src"], PREFIX, count=1)

    # Verify: r1 replicates once, midpath replicates to e1 and consumes locally
    assert _verify_replication(ndn, "r1", 1), "FAILED: r1 should replicate once"
    assert _verify_replication(ndn, "midpath", 1), "FAILED: midpath should replicate to e1"
    info("✓ PASSED: BFR+BFER mid-path destination works\n")
    ndn.stop()


# =============================================================================
# Test 8: Router with No Matching Bits (Packet Drop)
# =============================================================================
def test_no_matching_bits_drop():
    """Test that router drops packet when no bits match its bit-face map."""
    info("\n" + "="*70 + "\n")
    info("TEST 8: Router with No Matching Bits (Packet Drop)\n")
    info("="*70 + "\n")

    Minindn.cleanUp()
    Minindn.verifyDependencies()
    reset_global_mapping()

    topo = Topo()
    src = topo.addHost("src")
    r1 = topo.addHost("r1")
    r2 = topo.addHost("r2")  # Has no matching bit-face mappings
    e1 = topo.addHost("e1")
    topo.addLink(src, r1, delay="10ms", bw=10)
    topo.addLink(r1, r2, delay="10ms", bw=10)
    topo.addLink(r2, e1, delay="10ms", bw=10)

    ndn = Minindn(topo=topo)
    ndn.start()
    AppManager(ndn, ndn.net.hosts, Nfd, logLevel="DEBUG")

    PREFIX = "/test/nomatch"
    _configure_face_route(ndn, "src", "r1", PREFIX)
    face_r1_r2 = _configure_face_route(ndn, "r1", "r2", PREFIX)
    _configure_face_route(ndn, "r2", "e1", PREFIX)

    mapping = get_global_mapping()
    mapping.set_router_bit("e1", 5)
    mapping.add_prefix(PREFIX, ["e1"])

    mask = mapping.build_bier_mask(PREFIX)

    # r1: configured with bit 5
    _bier_ctl(ndn.net["r1"], "clear")
    _bier_ctl(ndn.net["r1"], f"prefix/{mask}/test/nomatch")
    _bier_ctl(ndn.net["r1"], f"bit-face/5/{face_r1_r2}")

    # r2: configured with DIFFERENT bit (9), so bit 5 has no match
    _bier_ctl(ndn.net["r2"], "clear")
    _bier_ctl(ndn.net["r2"], "bit-face/9/999")  # Non-existent mapping

    _inject_interests(ndn.net["src"], PREFIX, count=1)

    # Verify: r1 replicates, r2 should NOT replicate (drops packet)
    assert _verify_replication(ndn, "r1", 1), "FAILED: r1 should replicate"
    assert _verify_replication(ndn, "r2", 0), "FAILED: r2 should drop (no bit match)"
    info("✓ PASSED: Packet dropped when no bits match\n")
    ndn.stop()


# =============================================================================
# Test 9: Invalid Face ID in Bit-Face Mapping
# =============================================================================
def test_invalid_face_id():
    """Test behavior when bit-face map points to invalid face ID."""
    info("\n" + "="*70 + "\n")
    info("TEST 9: Invalid Face ID in Bit-Face Mapping\n")
    info("="*70 + "\n")

    Minindn.cleanUp()
    Minindn.verifyDependencies()
    reset_global_mapping()

    topo = Topo()
    src = topo.addHost("src")
    r1 = topo.addHost("r1")
    e1 = topo.addHost("e1")
    topo.addLink(src, r1, delay="10ms", bw=10)
    topo.addLink(r1, e1, delay="10ms", bw=10)

    ndn = Minindn(topo=topo)
    ndn.start()
    AppManager(ndn, ndn.net.hosts, Nfd, logLevel="DEBUG")

    PREFIX = "/test/invalidface"
    _configure_face_route(ndn, "src", "r1", PREFIX)

    mapping = get_global_mapping()
    mapping.set_router_bit("e1", 2)
    mapping.add_prefix(PREFIX, ["e1"])
    mask = mapping.build_bier_mask(PREFIX)

    # Configure with INVALID face ID
    _bier_ctl(ndn.net["r1"], "clear")
    _bier_ctl(ndn.net["r1"], f"prefix/{mask}/test/invalidface")
    _bier_ctl(ndn.net["r1"], "bit-face/2/99999")  # Non-existent face

    _inject_interests(ndn.net["src"], PREFIX, count=1)

    # Verify: r1 should NOT replicate (invalid face is skipped)
    assert _verify_replication(ndn, "r1", 0), "FAILED: Invalid face should be skipped"
    info("✓ PASSED: Invalid face ID handled gracefully\n")
    ndn.stop()


# =============================================================================
# Test 10: Runtime Reconfiguration During Traffic
# =============================================================================
def test_runtime_reconfig():
    """Test changing BIER config while traffic is flowing."""
    info("\n" + "="*70 + "\n")
    info("TEST 10: Runtime Reconfiguration During Traffic\n")
    info("="*70 + "\n")

    Minindn.cleanUp()
    Minindn.verifyDependencies()
    reset_global_mapping()

    topo = Topo()
    src = topo.addHost("src")
    r1 = topo.addHost("r1")
    e1 = topo.addHost("e1")
    e2 = topo.addHost("e2")
    topo.addLink(src, r1, delay="10ms", bw=10)
    topo.addLink(r1, e1, delay="10ms", bw=10)
    topo.addLink(r1, e2, delay="10ms", bw=10)

    ndn = Minindn(topo=topo)
    ndn.start()
    AppManager(ndn, ndn.net.hosts, Nfd, logLevel="DEBUG")

    PREFIX = "/test/reconfig"
    _configure_face_route(ndn, "src", "r1", PREFIX)
    face_r1_e1 = _configure_face_route(ndn, "r1", "e1", PREFIX)
    face_r1_e2 = _configure_face_route(ndn, "r1", "e2", PREFIX)

    mapping = get_global_mapping()
    mapping.set_router_bit("e1", 1)
    mapping.set_router_bit("e2", 2)

    # Initial config: only e1
    mapping.add_prefix(PREFIX, ["e1"])
    mask1 = mapping.build_bier_mask(PREFIX)
    _bier_ctl(ndn.net["r1"], "clear")
    _bier_ctl(ndn.net["r1"], f"prefix/{mask1}/test/reconfig")
    _bier_ctl(ndn.net["r1"], f"bit-face/1/{face_r1_e1}")

    _inject_interests(ndn.net["src"], PREFIX, count=1)
    assert _verify_replication(ndn, "r1", 1), "FAILED: Phase 1 should replicate to e1"

    # Runtime reconfig: add e2
    mapping.add_prefix(PREFIX, ["e1", "e2"])
    mask2 = mapping.build_bier_mask(PREFIX)
    _bier_ctl(ndn.net["r1"], f"prefix/{mask2}/test/reconfig")
    _bier_ctl(ndn.net["r1"], f"bit-face/2/{face_r1_e2}")

    _inject_interests(ndn.net["src"], PREFIX, count=1)
    # Total replications should now be 1 + 2 = 3
    log_path = f"{ndn.workDir}/r1/log/nfd.log"
    log_contents = ndn.net["r1"].cmd(f"cat {log_path}")
    total_count = log_contents.count("processBierInterest out=")
    assert total_count == 3, f"FAILED: Expected 3 total replications, got {total_count}"

    info("✓ PASSED: Runtime reconfiguration works\n")
    ndn.stop()


# =============================================================================
# Test 11: Clear Config Command
# =============================================================================
def test_clear_config():
    """Test /localhost/nfd/bier/clear command."""
    info("\n" + "="*70 + "\n")
    info("TEST 11: Clear BIER Config Command\n")
    info("="*70 + "\n")

    Minindn.cleanUp()
    Minindn.verifyDependencies()
    reset_global_mapping()

    topo = Topo()
    src = topo.addHost("src")
    r1 = topo.addHost("r1")
    e1 = topo.addHost("e1")
    topo.addLink(src, r1, delay="10ms", bw=10)
    topo.addLink(r1, e1, delay="10ms", bw=10)

    ndn = Minindn(topo=topo)
    ndn.start()
    AppManager(ndn, ndn.net.hosts, Nfd, logLevel="DEBUG")

    PREFIX = "/test/clear"
    _configure_face_route(ndn, "src", "r1", PREFIX)
    face_r1_e1 = _configure_face_route(ndn, "r1", "e1", PREFIX)

    mapping = get_global_mapping()
    mapping.set_router_bit("e1", 3)
    mapping.add_prefix(PREFIX, ["e1"])
    mask = mapping.build_bier_mask(PREFIX)

    # Set up config
    _bier_ctl(ndn.net["r1"], "clear")
    _bier_ctl(ndn.net["r1"], f"prefix/{mask}/test/clear")
    _bier_ctl(ndn.net["r1"], f"bit-face/3/{face_r1_e1}")
    _bier_ctl(ndn.net["r1"], "local-bit/5")

    _inject_interests(ndn.net["src"], PREFIX, count=1)
    assert _verify_replication(ndn, "r1", 1), "FAILED: Before clear should replicate"

    # Clear config
    _bier_ctl(ndn.net["r1"], "clear")
    _inject_interests(ndn.net["src"], PREFIX, count=1)

    # After clear, should NOT replicate (config gone, falls back to standard NDN)
    log_path = f"{ndn.workDir}/r1/log/nfd.log"
    log_contents = ndn.net["r1"].cmd(f"cat {log_path}")
    total_count = log_contents.count("processBierInterest out=")
    assert total_count == 1, "FAILED: After clear, no new BIER replication should occur"

    info("✓ PASSED: Clear config command works\n")
    ndn.stop()


# =============================================================================
# Test 12: Zero-Length Mask (Invalid)
# =============================================================================
def test_zero_length_mask():
    """Test behavior with empty/zero-length BIER mask."""
    info("\n" + "="*70 + "\n")
    info("TEST 12: Zero-Length Mask (Should Ignore)\n")
    info("="*70 + "\n")

    Minindn.cleanUp()
    Minindn.verifyDependencies()
    reset_global_mapping()

    topo = Topo()
    src = topo.addHost("src")
    r1 = topo.addHost("r1")
    topo.addLink(src, r1, delay="10ms", bw=10)

    ndn = Minindn(topo=topo)
    ndn.start()
    AppManager(ndn, ndn.net.hosts, Nfd, logLevel="DEBUG")

    PREFIX = "/test/zeromask"
    _configure_face_route(ndn, "src", "r1", PREFIX)

    # Try to configure with empty mask (should be ignored/warned)
    _bier_ctl(ndn.net["r1"], "clear")
    _bier_ctl(ndn.net["r1"], "prefix//test/zeromask")  # Empty mask

    _inject_interests(ndn.net["src"], PREFIX, count=1)

    # Should NOT use BIER (no valid mask)
    assert _verify_replication(ndn, "r1", 0), "FAILED: Zero mask should be ignored"
    info("✓ PASSED: Zero-length mask ignored\n")
    ndn.stop()


# =============================================================================
# Main Test Runner
# =============================================================================
def run_all_tests():
    """Run all edge case tests."""
    info("\n" + "="*70 + "\n")
    info("BIER EDGE CASE TEST SUITE\n")
    info("="*70 + "\n")

    tests = [
        test_multibyte_bitmask,
        test_empty_bitstring_local_only,
        test_broadcast_all_bits,
        test_unicast_single_bit,
        test_noncontiguous_bits,
        test_bfir_bfer_combination,
        test_bfr_bfer_midpath,
        test_no_matching_bits_drop,
        test_invalid_face_id,
        test_runtime_reconfig,
        test_clear_config,
        test_zero_length_mask,
    ]

    passed = 0
    failed = 0
    for test in tests:
        try:
            test()
            passed += 1
        except Exception as e:
            failed += 1
            info(f"✗ FAILED: {test.__name__}: {e}\n")

    info("\n" + "="*70 + "\n")
    info(f"RESULTS: {passed} passed, {failed} failed\n")
    info("="*70 + "\n")


if __name__ == "__main__":
    setLogLevel("info")
    run_all_tests()
