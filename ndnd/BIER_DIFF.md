# BIER Integration: Diff vs upstream named-data/ndnd@dv2

This repo adds BIER (Bit Index Explicit Replication) multicast support on top of
the upstream `dv2` branch. All changes are backward-compatible; non-BIER traffic
is unaffected.

---

## New Files (not in upstream)

| File | Purpose |
|------|---------|
| `fw/fw/bier.go` (296 lines) | BIFT table, bit-string helpers (`BierClone`, `BierClearBit`, `BierIsZero`, `BuildBierBitString`) |
| `fw/fw/bier_strategy.go` (157 lines) | `BierStrategy` — PIT-tandem BIER forwarding; replicates Interest per-bit via `SendInterest` |
| `fw/mgmt/bift.go` (95 lines) | Management face handler for BIER Forwarding Information Base Table (BIFT) |
| `cmd/svs-chat/main.go` | SVS ALO chat CLI demo that exercises BIER multicast sync |
| `fw/bier_tests/` | Unit + integration tests for BIER (4 files) |
| `e2e/test_005.py` | E2E test: BIER multicast on 52-node Sprint topology (51/51 consumers OK) |
| `e2e/test_006.py` | E2E test: multi-group BIER (two concurrent prefixes) |
| `e2e/test_007.py` | E2E test: SVS Chat over BIER (4/4 consumers receive message) |
| `e2e-run.sh` | Docker entrypoint: installs binaries, fake `go` shim, runs Mininet tests |
| `run-bier-e2e.sh` | macOS helper: cross-compiles Linux binaries, launches Docker |

---

## Modified Files

### `fw/core/config.go`
- Added `BierIndex int` field (`bier_index`) to `FwConfig` struct (line 121)
- Default value `-1` (disabled) set in `DefaultConfig()` (line 223)
- Operators set `bier_index: N` in YAML config to enable BIER on a node

### `fw/face/ndnlp-link-service.go`
- `sendPacket()` (line 262): copies `packet.Bier` onto the NDNLPv2 fragment TLV `0x035a` for outgoing Interests
- `handleIncomingFrame()` (line 356): reads `LP.Bier` from incoming frame and attaches it to the parsed packet

### `fw/fw/thread.go`
Three logical additions in `processOutgoingInterest`:

1. **BFER+BFR combined delivery** (line 372): after local PIT match, clear the local bit from the bit-string and fall through to network replication (so a node that is both a consumer and a transit BFR still forwards to remaining bits)

2. **BFIR encoding** (line 403): when `twoPhaseLookup` returns >1 egress router and `IsBierEnabled()`, call `Bift.BuildBierBitString()` to pre-encode a bit-string on the outgoing packet

3. **Auto-strategy selection** (line 412): when `packet.Bier != nil`, override the strategy to `BierStrategy` so bit-level replication runs through the PIT (PIT-tandem design)

---

## Architecture in One Paragraph

BIER piggybacks on NDNLPv2 via TLV `0x035a`. The BFIR (first-hop router) detects
multicast topology (>1 egress router in FIB) and stamps a bit-string onto the
Interest. `BierStrategy` then replicates the Interest once per set bit, sending
one copy per downstream router through the normal PIT machinery. Each BFR clears
its own bit before forwarding, so no router receives a copy destined only for it;
the Interest naturally terminates when all bits are cleared. BFER nodes deliver
locally and then re-forward any remaining bits. No bypass of the PIT occurs.
