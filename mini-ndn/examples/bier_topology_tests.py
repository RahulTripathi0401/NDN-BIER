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
BIER Topology Tests

Tests for complex multicast topologies:
- Diamond topology (multiple paths to same BFER)
- Tree topology (1 BFIR → N BFRs → M BFERs)
- Partial mesh topology (redundant BFR connections)
- Star topology (single BFR hub)
- Asymmetric tree (unbalanced fanout)
"""

import sys
import platform

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
    from minindn.minindn import Minindn
    from minindn.apps.app_manager import AppManager
    from minindn.apps.nfd import Nfd
    from minindn.helpers.nfdc import Nfdc
except ImportError as e:
    print(f"ERROR: {e}")
    print("\nMini-NDN/Mininet not installed. On Ubuntu/Debian:")
    print("  sudo apt-get update")
    print("  sudo apt-get install mininet python3-mininet")
    print("  cd mini-ndn && sudo ./install.sh --source")
    sys.exit(1)

from global_prefix_mapping import get_global_mapping, reset_global_mapping


def _bier_ctl(node, cmd):
    """Send BIER control command."""
    node.cmd(f"ndnpeek -w 80 /localhost/nfd/bier/{cmd} >/dev/null 2>&1 || true")


def _configure_face_route(ndn, src, dst, prefix):
    """Configure face and route between nodes."""
    src_node = ndn.net[src]
    dst_node = ndn.net[dst]
    dst_ip = dst_node.connectionsTo(src_node)[0][0].IP()
    face_id = Nfdc.createFace(src_node, dst_ip)
    Nfdc.registerRoute(src_node, prefix, dst_ip, cost=0)
    return face_id


def _inject_interests(node, prefix, count=1):
    """Inject test Interests."""
    for _ in range(count):
        node.cmd(f"ndnpeek -w 80 {prefix} >/dev/null 2>&1 || true")


def _verify_replication(ndn, router_name, expected_count):
    """Verify BIER replication count."""
    log_path = f"{ndn.workDir}/{router_name}/log/nfd.log"
    log_contents = ndn.net[router_name].cmd(f"cat {log_path}")
    actual_count = log_contents.count("processBierInterest out=")
    info(f"  {router_name}: expected={expected_count}, actual={actual_count}\n")
    return actual_count == expected_count


# =============================================================================
# Test 1: Diamond Topology (Multiple Paths to Same BFER)
# =============================================================================
def test_diamond_topology():
    """
    Test diamond topology with redundant paths.

    Topology:
         src
          |
          r1 (BFIR)
         / \\
        r2  r3 (BFRs)
         \\ /
          e1 (BFER)

    Both r2 and r3 should forward to e1, but e1 should only receive once
    due to BIER bit-string logic.
    """
    info("\n" + "="*70 + "\n")
    info("TEST 1: Diamond Topology (Redundant Paths)\n")
    info("="*70 + "\n")

    Minindn.cleanUp()
    Minindn.verifyDependencies()
    reset_global_mapping()

    topo = Topo()
    src = topo.addHost("src")
    r1 = topo.addHost("r1")
    r2 = topo.addHost("r2")
    r3 = topo.addHost("r3")
    e1 = topo.addHost("e1")

    topo.addLink(src, r1, delay="10ms", bw=10)
    topo.addLink(r1, r2, delay="10ms", bw=10)
    topo.addLink(r1, r3, delay="10ms", bw=10)
    topo.addLink(r2, e1, delay="10ms", bw=10)
    topo.addLink(r3, e1, delay="10ms", bw=10)

    ndn = Minindn(topo=topo)
    ndn.start()
    AppManager(ndn, ndn.net.hosts, Nfd, logLevel="DEBUG")

    PREFIX = "/test/diamond"

    # Configure faces
    _configure_face_route(ndn, "src", "r1", PREFIX)
    face_r1_r2 = _configure_face_route(ndn, "r1", "r2", PREFIX)
    face_r1_r3 = _configure_face_route(ndn, "r1", "r3", PREFIX)
    face_r2_e1 = _configure_face_route(ndn, "r2", "e1", PREFIX)
    face_r3_e1 = _configure_face_route(ndn, "r3", "e1", PREFIX)

    # Set up global mapping
    mapping = get_global_mapping()
    mapping.set_router_bit("e1", 5)
    mapping.add_prefix(PREFIX, ["e1"])
    mask = mapping.build_bier_mask(PREFIX)

    # Configure BFIR (r1)
    _bier_ctl(ndn.net["r1"], "clear")
    _bier_ctl(ndn.net["r1"], f"prefix/{mask}/test/diamond")
    _bier_ctl(ndn.net["r1"], f"bit-face/5/{face_r1_r2}")
    _bier_ctl(ndn.net["r1"], f"bit-face/5/{face_r1_r3}")  # Same bit, different face

    # Configure BFRs (r2, r3)
    _bier_ctl(ndn.net["r2"], "clear")
    _bier_ctl(ndn.net["r2"], f"bit-face/5/{face_r2_e1}")

    _bier_ctl(ndn.net["r3"], "clear")
    _bier_ctl(ndn.net["r3"], f"bit-face/5/{face_r3_e1}")

    # Configure BFER (e1)
    _bier_ctl(ndn.net["e1"], "clear")
    _bier_ctl(ndn.net["e1"], "local-bit/5")

    _inject_interests(ndn.net["src"], PREFIX, count=1)

    # Verify: r1 should replicate to BOTH r2 and r3
    # Note: Current implementation may send to both or just one (depends on BIFT logic)
    # For now, we expect r1 to replicate once per unique face
    assert _verify_replication(ndn, "r1", 2), "FAILED: r1 should replicate to both r2 and r3"
    assert _verify_replication(ndn, "r2", 1), "FAILED: r2 should forward to e1"
    assert _verify_replication(ndn, "r3", 1), "FAILED: r3 should forward to e1"

    info("✓ PASSED: Diamond topology handled\n")
    ndn.stop()


# =============================================================================
# Test 2: Tree Topology (1 BFIR → 3 BFRs → 6 BFERs)
# =============================================================================
def test_tree_topology():
    """
    Test balanced tree topology.

    Topology:
              src
               |
              r1 (BFIR)
            / | \\
           /  |  \\
          r2  r3  r4 (BFRs)
         / \\  / \\  / \\
        e1 e2 e3 e4 e5 e6 (BFERs)
    """
    info("\n" + "="*70 + "\n")
    info("TEST 2: Tree Topology (1→3→6)\n")
    info("="*70 + "\n")

    Minindn.cleanUp()
    Minindn.verifyDependencies()
    reset_global_mapping()

    topo = Topo()
    src = topo.addHost("src")
    r1 = topo.addHost("r1")
    r2 = topo.addHost("r2")
    r3 = topo.addHost("r3")
    r4 = topo.addHost("r4")
    e1 = topo.addHost("e1")
    e2 = topo.addHost("e2")
    e3 = topo.addHost("e3")
    e4 = topo.addHost("e4")
    e5 = topo.addHost("e5")
    e6 = topo.addHost("e6")

    topo.addLink(src, r1, delay="10ms", bw=10)
    topo.addLink(r1, r2, delay="10ms", bw=10)
    topo.addLink(r1, r3, delay="10ms", bw=10)
    topo.addLink(r1, r4, delay="10ms", bw=10)
    topo.addLink(r2, e1, delay="10ms", bw=10)
    topo.addLink(r2, e2, delay="10ms", bw=10)
    topo.addLink(r3, e3, delay="10ms", bw=10)
    topo.addLink(r3, e4, delay="10ms", bw=10)
    topo.addLink(r4, e5, delay="10ms", bw=10)
    topo.addLink(r4, e6, delay="10ms", bw=10)

    ndn = Minindn(topo=topo)
    ndn.start()
    AppManager(ndn, ndn.net.hosts, Nfd, logLevel="DEBUG")

    PREFIX = "/test/tree"

    # Configure faces
    _configure_face_route(ndn, "src", "r1", PREFIX)
    face_r1_r2 = _configure_face_route(ndn, "r1", "r2", PREFIX)
    face_r1_r3 = _configure_face_route(ndn, "r1", "r3", PREFIX)
    face_r1_r4 = _configure_face_route(ndn, "r1", "r4", PREFIX)

    face_r2_e1 = _configure_face_route(ndn, "r2", "e1", PREFIX)
    face_r2_e2 = _configure_face_route(ndn, "r2", "e2", PREFIX)
    face_r3_e3 = _configure_face_route(ndn, "r3", "e3", PREFIX)
    face_r3_e4 = _configure_face_route(ndn, "r3", "e4", PREFIX)
    face_r4_e5 = _configure_face_route(ndn, "r4", "e5", PREFIX)
    face_r4_e6 = _configure_face_route(ndn, "r4", "e6", PREFIX)

    # Set up global mapping
    mapping = get_global_mapping()
    egress_routers = ["e1", "e2", "e3", "e4", "e5", "e6"]
    for i, router in enumerate(egress_routers):
        mapping.set_router_bit(router, i)
    mapping.add_prefix(PREFIX, egress_routers)
    mask = mapping.build_bier_mask(PREFIX)

    # Configure BFIR (r1)
    _bier_ctl(ndn.net["r1"], "clear")
    _bier_ctl(ndn.net["r1"], f"prefix/{mask}/test/tree")
    _bier_ctl(ndn.net["r1"], f"bit-face/0/{face_r1_r2}")  # e1
    _bier_ctl(ndn.net["r1"], f"bit-face/1/{face_r1_r2}")  # e2
    _bier_ctl(ndn.net["r1"], f"bit-face/2/{face_r1_r3}")  # e3
    _bier_ctl(ndn.net["r1"], f"bit-face/3/{face_r1_r3}")  # e4
    _bier_ctl(ndn.net["r1"], f"bit-face/4/{face_r1_r4}")  # e5
    _bier_ctl(ndn.net["r1"], f"bit-face/5/{face_r1_r4}")  # e6

    # Configure BFRs
    _bier_ctl(ndn.net["r2"], "clear")
    _bier_ctl(ndn.net["r2"], f"bit-face/0/{face_r2_e1}")
    _bier_ctl(ndn.net["r2"], f"bit-face/1/{face_r2_e2}")

    _bier_ctl(ndn.net["r3"], "clear")
    _bier_ctl(ndn.net["r3"], f"bit-face/2/{face_r3_e3}")
    _bier_ctl(ndn.net["r3"], f"bit-face/3/{face_r3_e4}")

    _bier_ctl(ndn.net["r4"], "clear")
    _bier_ctl(ndn.net["r4"], f"bit-face/4/{face_r4_e5}")
    _bier_ctl(ndn.net["r4"], f"bit-face/5/{face_r4_e6}")

    # Configure BFERs
    for i, router in enumerate(egress_routers):
        _bier_ctl(ndn.net[router], "clear")
        _bier_ctl(ndn.net[router], f"local-bit/{i}")

    _inject_interests(ndn.net["src"], PREFIX, count=1)

    # Verify: r1 replicates to 3 BFRs, each BFR replicates to 2 BFERs
    assert _verify_replication(ndn, "r1", 3), "FAILED: r1 should replicate to 3 BFRs"
    assert _verify_replication(ndn, "r2", 2), "FAILED: r2 should replicate to 2 BFERs"
    assert _verify_replication(ndn, "r3", 2), "FAILED: r3 should replicate to 2 BFERs"
    assert _verify_replication(ndn, "r4", 2), "FAILED: r4 should replicate to 2 BFERs"

    info("✓ PASSED: Tree topology handled\n")
    ndn.stop()


# =============================================================================
# Test 3: Partial Mesh Topology
# =============================================================================
def test_partial_mesh():
    """
    Test partial mesh with redundant BFR connections.

    Topology:
         src
          |
          r1 (BFIR)
         /|\\
        / | \\
       r2-r3-r4 (BFRs, interconnected)
       |  |  |
       e1 e2 e3 (BFERs)
    """
    info("\n" + "="*70 + "\n")
    info("TEST 3: Partial Mesh Topology\n")
    info("="*70 + "\n")

    Minindn.cleanUp()
    Minindn.verifyDependencies()
    reset_global_mapping()

    topo = Topo()
    src = topo.addHost("src")
    r1 = topo.addHost("r1")
    r2 = topo.addHost("r2")
    r3 = topo.addHost("r3")
    r4 = topo.addHost("r4")
    e1 = topo.addHost("e1")
    e2 = topo.addHost("e2")
    e3 = topo.addHost("e3")

    topo.addLink(src, r1, delay="10ms", bw=10)
    topo.addLink(r1, r2, delay="10ms", bw=10)
    topo.addLink(r1, r3, delay="10ms", bw=10)
    topo.addLink(r1, r4, delay="10ms", bw=10)
    # Mesh connections between BFRs
    topo.addLink(r2, r3, delay="10ms", bw=10)
    topo.addLink(r3, r4, delay="10ms", bw=10)
    # BFR to BFER
    topo.addLink(r2, e1, delay="10ms", bw=10)
    topo.addLink(r3, e2, delay="10ms", bw=10)
    topo.addLink(r4, e3, delay="10ms", bw=10)

    ndn = Minindn(topo=topo)
    ndn.start()
    AppManager(ndn, ndn.net.hosts, Nfd, logLevel="DEBUG")

    PREFIX = "/test/mesh"

    # Configure faces
    _configure_face_route(ndn, "src", "r1", PREFIX)
    face_r1_r2 = _configure_face_route(ndn, "r1", "r2", PREFIX)
    face_r1_r3 = _configure_face_route(ndn, "r1", "r3", PREFIX)
    face_r1_r4 = _configure_face_route(ndn, "r1", "r4", PREFIX)

    face_r2_e1 = _configure_face_route(ndn, "r2", "e1", PREFIX)
    face_r3_e2 = _configure_face_route(ndn, "r3", "e2", PREFIX)
    face_r4_e3 = _configure_face_route(ndn, "r4", "e3", PREFIX)

    # Set up global mapping
    mapping = get_global_mapping()
    mapping.set_router_bit("e1", 10)
    mapping.set_router_bit("e2", 11)
    mapping.set_router_bit("e3", 12)
    mapping.add_prefix(PREFIX, ["e1", "e2", "e3"])
    mask = mapping.build_bier_mask(PREFIX)

    # Configure BFIR (r1)
    _bier_ctl(ndn.net["r1"], "clear")
    _bier_ctl(ndn.net["r1"], f"prefix/{mask}/test/mesh")
    _bier_ctl(ndn.net["r1"], f"bit-face/10/{face_r1_r2}")
    _bier_ctl(ndn.net["r1"], f"bit-face/11/{face_r1_r3}")
    _bier_ctl(ndn.net["r1"], f"bit-face/12/{face_r1_r4}")

    # Configure BFRs
    _bier_ctl(ndn.net["r2"], "clear")
    _bier_ctl(ndn.net["r2"], f"bit-face/10/{face_r2_e1}")

    _bier_ctl(ndn.net["r3"], "clear")
    _bier_ctl(ndn.net["r3"], f"bit-face/11/{face_r3_e2}")

    _bier_ctl(ndn.net["r4"], "clear")
    _bier_ctl(ndn.net["r4"], f"bit-face/12/{face_r4_e3}")

    # Configure BFERs
    _bier_ctl(ndn.net["e1"], "clear")
    _bier_ctl(ndn.net["e1"], "local-bit/10")
    _bier_ctl(ndn.net["e2"], "clear")
    _bier_ctl(ndn.net["e2"], "local-bit/11")
    _bier_ctl(ndn.net["e3"], "clear")
    _bier_ctl(ndn.net["e3"], "local-bit/12")

    _inject_interests(ndn.net["src"], PREFIX, count=1)

    # Verify
    assert _verify_replication(ndn, "r1", 3), "FAILED: r1 should replicate to 3 BFRs"
    assert _verify_replication(ndn, "r2", 1), "FAILED: r2 should replicate to e1"
    assert _verify_replication(ndn, "r3", 1), "FAILED: r3 should replicate to e2"
    assert _verify_replication(ndn, "r4", 1), "FAILED: r4 should replicate to e3"

    info("✓ PASSED: Partial mesh topology handled\n")
    ndn.stop()


# =============================================================================
# Test 4: Star Topology (Single Hub BFR)
# =============================================================================
def test_star_topology():
    """
    Test star topology with single central BFR.

    Topology:
         src
          |
          r1 (BFIR)
          |
          hub (BFR)
         /|\\\
        / | \\
       e1 e2 e3 e4 (BFERs)
    """
    info("\n" + "="*70 + "\n")
    info("TEST 4: Star Topology (Single Hub)\n")
    info("="*70 + "\n")

    Minindn.cleanUp()
    Minindn.verifyDependencies()
    reset_global_mapping()

    topo = Topo()
    src = topo.addHost("src")
    r1 = topo.addHost("r1")
    hub = topo.addHost("hub")
    e1 = topo.addHost("e1")
    e2 = topo.addHost("e2")
    e3 = topo.addHost("e3")
    e4 = topo.addHost("e4")

    topo.addLink(src, r1, delay="10ms", bw=10)
    topo.addLink(r1, hub, delay="10ms", bw=10)
    topo.addLink(hub, e1, delay="10ms", bw=10)
    topo.addLink(hub, e2, delay="10ms", bw=10)
    topo.addLink(hub, e3, delay="10ms", bw=10)
    topo.addLink(hub, e4, delay="10ms", bw=10)

    ndn = Minindn(topo=topo)
    ndn.start()
    AppManager(ndn, ndn.net.hosts, Nfd, logLevel="DEBUG")

    PREFIX = "/test/star"

    # Configure faces
    _configure_face_route(ndn, "src", "r1", PREFIX)
    face_r1_hub = _configure_face_route(ndn, "r1", "hub", PREFIX)
    face_hub_e1 = _configure_face_route(ndn, "hub", "e1", PREFIX)
    face_hub_e2 = _configure_face_route(ndn, "hub", "e2", PREFIX)
    face_hub_e3 = _configure_face_route(ndn, "hub", "e3", PREFIX)
    face_hub_e4 = _configure_face_route(ndn, "hub", "e4", PREFIX)

    # Set up global mapping
    mapping = get_global_mapping()
    egress_routers = ["e1", "e2", "e3", "e4"]
    for i, router in enumerate(egress_routers):
        mapping.set_router_bit(router, i + 20)
    mapping.add_prefix(PREFIX, egress_routers)
    mask = mapping.build_bier_mask(PREFIX)

    # Configure BFIR (r1)
    _bier_ctl(ndn.net["r1"], "clear")
    _bier_ctl(ndn.net["r1"], f"prefix/{mask}/test/star")
    for i in range(4):
        _bier_ctl(ndn.net["r1"], f"bit-face/{i+20}/{face_r1_hub}")

    # Configure Hub BFR
    _bier_ctl(ndn.net["hub"], "clear")
    _bier_ctl(ndn.net["hub"], f"bit-face/20/{face_hub_e1}")
    _bier_ctl(ndn.net["hub"], f"bit-face/21/{face_hub_e2}")
    _bier_ctl(ndn.net["hub"], f"bit-face/22/{face_hub_e3}")
    _bier_ctl(ndn.net["hub"], f"bit-face/23/{face_hub_e4}")

    # Configure BFERs
    for i, router in enumerate(egress_routers):
        _bier_ctl(ndn.net[router], "clear")
        _bier_ctl(ndn.net[router], f"local-bit/{i+20}")

    _inject_interests(ndn.net["src"], PREFIX, count=1)

    # Verify
    assert _verify_replication(ndn, "r1", 1), "FAILED: r1 should replicate once to hub"
    assert _verify_replication(ndn, "hub", 4), "FAILED: hub should replicate to 4 BFERs"

    info("✓ PASSED: Star topology handled\n")
    ndn.stop()


# =============================================================================
# Test 5: Asymmetric Tree (Unbalanced Fanout)
# =============================================================================
def test_asymmetric_tree():
    """
    Test asymmetric tree with unbalanced fanout.

    Topology:
         src
          |
          r1 (BFIR)
         / \\
        /   \\
       r2    r3
       |    / | \\
       e1  e2 e3 e4
    """
    info("\n" + "="*70 + "\n")
    info("TEST 5: Asymmetric Tree (Unbalanced Fanout)\n")
    info("="*70 + "\n")

    Minindn.cleanUp()
    Minindn.verifyDependencies()
    reset_global_mapping()

    topo = Topo()
    src = topo.addHost("src")
    r1 = topo.addHost("r1")
    r2 = topo.addHost("r2")
    r3 = topo.addHost("r3")
    e1 = topo.addHost("e1")
    e2 = topo.addHost("e2")
    e3 = topo.addHost("e3")
    e4 = topo.addHost("e4")

    topo.addLink(src, r1, delay="10ms", bw=10)
    topo.addLink(r1, r2, delay="10ms", bw=10)
    topo.addLink(r1, r3, delay="10ms", bw=10)
    topo.addLink(r2, e1, delay="10ms", bw=10)
    topo.addLink(r3, e2, delay="10ms", bw=10)
    topo.addLink(r3, e3, delay="10ms", bw=10)
    topo.addLink(r3, e4, delay="10ms", bw=10)

    ndn = Minindn(topo=topo)
    ndn.start()
    AppManager(ndn, ndn.net.hosts, Nfd, logLevel="DEBUG")

    PREFIX = "/test/asymmetric"

    # Configure faces
    _configure_face_route(ndn, "src", "r1", PREFIX)
    face_r1_r2 = _configure_face_route(ndn, "r1", "r2", PREFIX)
    face_r1_r3 = _configure_face_route(ndn, "r1", "r3", PREFIX)
    face_r2_e1 = _configure_face_route(ndn, "r2", "e1", PREFIX)
    face_r3_e2 = _configure_face_route(ndn, "r3", "e2", PREFIX)
    face_r3_e3 = _configure_face_route(ndn, "r3", "e3", PREFIX)
    face_r3_e4 = _configure_face_route(ndn, "r3", "e4", PREFIX)

    # Set up global mapping
    mapping = get_global_mapping()
    mapping.set_router_bit("e1", 30)
    mapping.set_router_bit("e2", 31)
    mapping.set_router_bit("e3", 32)
    mapping.set_router_bit("e4", 33)
    mapping.add_prefix(PREFIX, ["e1", "e2", "e3", "e4"])
    mask = mapping.build_bier_mask(PREFIX)

    # Configure BFIR (r1)
    _bier_ctl(ndn.net["r1"], "clear")
    _bier_ctl(ndn.net["r1"], f"prefix/{mask}/test/asymmetric")
    _bier_ctl(ndn.net["r1"], f"bit-face/30/{face_r1_r2}")
    _bier_ctl(ndn.net["r1"], f"bit-face/31/{face_r1_r3}")
    _bier_ctl(ndn.net["r1"], f"bit-face/32/{face_r1_r3}")
    _bier_ctl(ndn.net["r1"], f"bit-face/33/{face_r1_r3}")

    # Configure BFRs
    _bier_ctl(ndn.net["r2"], "clear")
    _bier_ctl(ndn.net["r2"], f"bit-face/30/{face_r2_e1}")

    _bier_ctl(ndn.net["r3"], "clear")
    _bier_ctl(ndn.net["r3"], f"bit-face/31/{face_r3_e2}")
    _bier_ctl(ndn.net["r3"], f"bit-face/32/{face_r3_e3}")
    _bier_ctl(ndn.net["r3"], f"bit-face/33/{face_r3_e4}")

    # Configure BFERs
    _bier_ctl(ndn.net["e1"], "clear")
    _bier_ctl(ndn.net["e1"], "local-bit/30")
    _bier_ctl(ndn.net["e2"], "clear")
    _bier_ctl(ndn.net["e2"], "local-bit/31")
    _bier_ctl(ndn.net["e3"], "clear")
    _bier_ctl(ndn.net["e3"], "local-bit/32")
    _bier_ctl(ndn.net["e4"], "clear")
    _bier_ctl(ndn.net["e4"], "local-bit/33")

    _inject_interests(ndn.net["src"], PREFIX, count=1)

    # Verify
    assert _verify_replication(ndn, "r1", 2), "FAILED: r1 should replicate to 2 BFRs"
    assert _verify_replication(ndn, "r2", 1), "FAILED: r2 should replicate to 1 BFER"
    assert _verify_replication(ndn, "r3", 3), "FAILED: r3 should replicate to 3 BFERs"

    info("✓ PASSED: Asymmetric tree handled\n")
    ndn.stop()


# =============================================================================
# Main Test Runner
# =============================================================================
def run_all_tests():
    """Run all topology tests."""
    info("\n" + "="*70 + "\n")
    info("BIER TOPOLOGY TEST SUITE\n")
    info("="*70 + "\n")

    tests = [
        test_diamond_topology,
        test_tree_topology,
        test_partial_mesh,
        test_star_topology,
        test_asymmetric_tree,
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
