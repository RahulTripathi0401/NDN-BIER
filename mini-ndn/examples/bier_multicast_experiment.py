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
#
# Mini-NDN is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with Mini-NDN, e.g., in COPYING.md file.
# If not, see <http://www.gnu.org/licenses/>.

from mininet.log import setLogLevel, info
from mininet.topo import Topo

from minindn.minindn import Minindn
from minindn.apps.app_manager import AppManager
from minindn.apps.nfd import Nfd
from minindn.apps.tshark import Tshark
from minindn.helpers.nfdc import Nfdc

PREFIX = "/bier/video/sync"

# Simulator-global table requested by experiment design.
GLOBAL_PREFIX_TO_EGRESS = {
    PREFIX: ["l1", "l2"],
}

ROUTER_BITS = {
    "l1": 0,
    "l2": 1,
}


def _name_to_suffix(prefix):
    return "/".join([comp for comp in prefix.split("/") if comp])


def _build_hex_mask(prefix):
    destinations = GLOBAL_PREFIX_TO_EGRESS[prefix]
    max_bit = max(ROUTER_BITS[node] for node in destinations)
    width = max_bit // 8 + 1
    mask = [0] * width
    for node in destinations:
        bit = ROUTER_BITS[node]
        byte_index = bit // 8
        bit_index = 7 - (bit % 8)
        mask[byte_index] |= 1 << bit_index
    return "".join(f"{byte:02X}" for byte in mask)


def _run_bier_ctl(node, cmd):
    node.cmd(f"ndnpeek -w 80 /localhost/nfd/bier/{cmd} >/dev/null 2>&1 || true")


def _configure_link_route(ndn, src, dst, prefix):
    src_node = ndn.net[src]
    dst_node = ndn.net[dst]
    dst_ip = dst_node.connectionsTo(src_node)[0][0].IP()
    face_id = Nfdc.createFace(src_node, dst_ip)
    Nfdc.registerRoute(src_node, prefix, dst_ip, cost=0)
    return face_id


def run():
    Minindn.cleanUp()
    Minindn.verifyDependencies()

    topo = Topo()
    src = topo.addHost("src")
    r1 = topo.addHost("r1")
    r2 = topo.addHost("r2")
    l1 = topo.addHost("l1")
    l2 = topo.addHost("l2")
    topo.addLink(src, r1, delay="10ms", bw=10)
    topo.addLink(r1, r2, delay="10ms", bw=10)
    topo.addLink(r2, l1, delay="10ms", bw=10)
    topo.addLink(r2, l2, delay="10ms", bw=10)

    ndn = Minindn(topo=topo)
    ndn.start()

    info("Starting packet capture\n")
    AppManager(ndn, ndn.net.hosts, Tshark, logFolder="./log/", singleLogFile=False)

    info("Starting NFD\n")
    AppManager(ndn, ndn.net.hosts, Nfd, logLevel="DEBUG")

    info("Configuring static faces and routes\n")
    _configure_link_route(ndn, "src", "r1", PREFIX)
    face_r1_to_r2 = _configure_link_route(ndn, "r1", "r2", PREFIX)
    face_r2_to_l1 = _configure_link_route(ndn, "r2", "l1", PREFIX)
    face_r2_to_l2 = _configure_link_route(ndn, "r2", "l2", PREFIX)

    # Reverse faces/routes for management and diagnostics convenience.
    _configure_link_route(ndn, "r1", "src", PREFIX)
    _configure_link_route(ndn, "r2", "r1", PREFIX)
    _configure_link_route(ndn, "l1", "r2", PREFIX)
    _configure_link_route(ndn, "l2", "r2", PREFIX)

    info("Programming BIER runtime state\n")
    for node_name in ["r1", "r2", "l1", "l2"]:
        _run_bier_ctl(ndn.net[node_name], "clear")

    # BFIR: route this prefix into a two-bit destination set (0 and 1).
    _run_bier_ctl(ndn.net["r1"], f"prefix/{_build_hex_mask(PREFIX)}/{_name_to_suffix(PREFIX)}")
    _run_bier_ctl(ndn.net["r1"], f"bit-face/0/{face_r1_to_r2}")
    _run_bier_ctl(ndn.net["r1"], f"bit-face/1/{face_r1_to_r2}")

    # BFR: split bit 0 and bit 1 toward different downstream leaves.
    _run_bier_ctl(ndn.net["r2"], f"bit-face/0/{face_r2_to_l1}")
    _run_bier_ctl(ndn.net["r2"], f"bit-face/1/{face_r2_to_l2}")

    # BFER local-bit settings.
    _run_bier_ctl(ndn.net["l1"], f"local-bit/{ROUTER_BITS['l1']}")
    _run_bier_ctl(ndn.net["l2"], f"local-bit/{ROUTER_BITS['l2']}")

    info("Injecting Interests to trigger BIER replication\n")
    for _ in range(3):
        ndn.net["src"].cmd(f"ndnpeek -w 80 {PREFIX} >/dev/null 2>&1 || true")

    r2_log = f"{ndn.workDir}/r2/log/nfd.log"
    log_contents = ndn.net["r2"].cmd(f"cat {r2_log}")
    replication_hits = log_contents.count("processBierInterest out=")
    info(f"BIER replication log hits at r2: {replication_hits}\n")
    info(ndn.net["r2"].cmd("nfdc face list"))
    info(ndn.net["r2"].cmd("nfdc fib list"))

    ndn.stop()


if __name__ == "__main__":
    setLogLevel("info")
    run()
