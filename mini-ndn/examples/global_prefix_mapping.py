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
Global Prefix-to-Router Mapping (Simulated PIB)

This module provides a simulated Prefix Information Base (PIB) that can be
shared across all routers in a Mini-NDN topology. In a real deployment, this
would be managed by ndn-pid daemon and distributed via routing protocols.

For testing purposes, this implements:
- Global hashtable of prefix -> [egress_router_names]
- Router name to BFR-ID (bit position) mapping
- Helper functions for BIER mask construction
"""

import threading
from typing import Dict, List, Set


class GlobalPrefixMapping:
    """
    Thread-safe global mapping accessible by all routers in the network.
    Simulates a distributed PIB for BIER testing.
    """

    def __init__(self):
        self._lock = threading.RLock()
        # Prefix -> List of egress router names
        self._prefix_to_routers: Dict[str, List[str]] = {}
        # Router name -> BFR-ID (bit position)
        self._router_to_bit: Dict[str, int] = {}
        # BFR-ID -> Router name (reverse lookup)
        self._bit_to_router: Dict[int, str] = {}

    def add_prefix(self, prefix: str, egress_routers: List[str]) -> None:
        """
        Add or update a prefix mapping.

        Args:
            prefix: NDN prefix (e.g., "/bier/video/sync")
            egress_routers: List of egress router names (e.g., ["l1", "l2"])
        """
        with self._lock:
            self._prefix_to_routers[prefix] = egress_routers.copy()

    def remove_prefix(self, prefix: str) -> None:
        """Remove a prefix mapping."""
        with self._lock:
            self._prefix_to_routers.pop(prefix, None)

    def get_egress_routers(self, prefix: str) -> List[str]:
        """
        Get egress routers for a prefix using longest prefix match.

        Args:
            prefix: NDN prefix to lookup

        Returns:
            List of egress router names, or empty list if no match
        """
        with self._lock:
            # Simple exact match for now; could implement LPM later
            return self._prefix_to_routers.get(prefix, []).copy()

    def set_router_bit(self, router_name: str, bit_position: int) -> None:
        """
        Assign a BFR-ID (bit position) to a router.

        Args:
            router_name: Name of the router (e.g., "l1")
            bit_position: Bit position in BIER bitstring (0-based)

        Raises:
            ValueError: If bit position is already assigned to another router
        """
        with self._lock:
            if bit_position in self._bit_to_router:
                existing = self._bit_to_router[bit_position]
                if existing != router_name:
                    raise ValueError(
                        f"Bit {bit_position} already assigned to {existing}"
                    )

            # Remove old bit assignment if router is being reassigned
            if router_name in self._router_to_bit:
                old_bit = self._router_to_bit[router_name]
                self._bit_to_router.pop(old_bit, None)

            self._router_to_bit[router_name] = bit_position
            self._bit_to_router[bit_position] = router_name

    def get_router_bit(self, router_name: str) -> int:
        """
        Get the BFR-ID for a router.

        Returns:
            Bit position, or -1 if not assigned
        """
        with self._lock:
            return self._router_to_bit.get(router_name, -1)

    def get_router_by_bit(self, bit_position: int) -> str:
        """
        Get the router name for a BFR-ID.

        Returns:
            Router name, or empty string if not assigned
        """
        with self._lock:
            return self._bit_to_router.get(bit_position, "")

    def build_bier_mask(self, prefix: str) -> str:
        """
        Build a BIER bitstring mask for a prefix using OR logic.

        Args:
            prefix: NDN prefix to lookup

        Returns:
            Hex-encoded BIER mask (e.g., "8040"), or empty string if no match
        """
        with self._lock:
            egress_routers = self._prefix_to_routers.get(prefix, [])
            if not egress_routers:
                return ""

            # Collect all bit positions
            bit_positions = []
            for router in egress_routers:
                bit = self._router_to_bit.get(router, -1)
                if bit >= 0:
                    bit_positions.append(bit)

            if not bit_positions:
                return ""

            # Calculate required byte width
            max_bit = max(bit_positions)
            width = max_bit // 8 + 1

            # Build mask array
            mask = [0] * width
            for bit in bit_positions:
                byte_index = bit // 8
                bit_index = 7 - (bit % 8)
                mask[byte_index] |= (1 << bit_index)

            # Convert to hex string
            return "".join(f"{byte:02X}" for byte in mask)

    def get_all_prefixes(self) -> List[str]:
        """Get all registered prefixes."""
        with self._lock:
            return list(self._prefix_to_routers.keys())

    def get_all_routers(self) -> List[str]:
        """Get all registered routers."""
        with self._lock:
            return list(self._router_to_bit.keys())

    def clear(self) -> None:
        """Clear all mappings."""
        with self._lock:
            self._prefix_to_routers.clear()
            self._router_to_bit.clear()
            self._bit_to_router.clear()

    def __repr__(self) -> str:
        with self._lock:
            return (
                f"GlobalPrefixMapping(\n"
                f"  Prefixes: {self._prefix_to_routers}\n"
                f"  Router bits: {self._router_to_bit}\n"
                f")"
            )


# Global singleton instance for use across all tests
_global_mapping = GlobalPrefixMapping()


def get_global_mapping() -> GlobalPrefixMapping:
    """Get the global singleton mapping instance."""
    return _global_mapping


def reset_global_mapping() -> None:
    """Reset the global mapping (useful for test isolation)."""
    _global_mapping.clear()
