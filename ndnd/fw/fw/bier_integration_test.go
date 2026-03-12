package fw

import (
	"sync"
	"testing"

	"github.com/named-data/ndnd/fw/core"
	"github.com/named-data/ndnd/fw/table"
	enc "github.com/named-data/ndnd/std/encoding"
)

// setBierIndex sets the global BierIndex config for test duration.
func setBierIndex(idx int) func() {
	old := core.C.Fw.BierIndex
	core.C.Fw.BierIndex = idx
	return func() { core.C.Fw.BierIndex = old }
}

// --- Bit-manipulation edge cases ---

func TestBierBitManipulationEdgeCases(t *testing.T) {
	t.Run("GetBit on empty slice returns false", func(t *testing.T) {
		if BierGetBit(nil, 0) {
			t.Error("GetBit on nil should be false")
		}
		if BierGetBit([]byte{}, 7) {
			t.Error("GetBit on empty slice should be false")
		}
	})

	t.Run("GetBit out-of-bounds returns false", func(t *testing.T) {
		bs := []byte{0xFF} // only byte 0
		if BierGetBit(bs, 8) {
			t.Error("GetBit at byte 1 of 1-byte slice should be false")
		}
		if BierGetBit(bs, 100) {
			t.Error("GetBit far out of bounds should be false")
		}
	})

	t.Run("SetBit auto-extends slice", func(t *testing.T) {
		var bs []byte
		bs = BierSetBit(bs, 23) // byte index 2
		if len(bs) < 3 {
			t.Errorf("slice should be at least 3 bytes, got %d", len(bs))
		}
		if !BierGetBit(bs, 23) {
			t.Error("bit 23 should be set")
		}
		// Preceding bytes should be zero
		if bs[0] != 0 || bs[1] != 0 {
			t.Error("lower bytes should be zero after setting bit 23 only")
		}
	})

	t.Run("SetBit boundary — bit 7 is MSB of first byte", func(t *testing.T) {
		var bs []byte
		bs = BierSetBit(bs, 7)
		if bs[0] != 0x80 {
			t.Errorf("expected 0x80, got %02x", bs[0])
		}
	})

	t.Run("SetBit boundary — bit 8 is LSB of second byte", func(t *testing.T) {
		var bs []byte
		bs = BierSetBit(bs, 8)
		if len(bs) < 2 || bs[1] != 0x01 {
			t.Errorf("expected second byte 0x01, got %v", bs)
		}
	})

	t.Run("ClearBit out-of-bounds is a no-op", func(t *testing.T) {
		bs := []byte{0xFF}
		BierClearBit(bs, 100) // should not panic
		if bs[0] != 0xFF {
			t.Error("ClearBit out-of-bounds should not modify the slice")
		}
	})

	t.Run("ClearBit on nil is a no-op", func(t *testing.T) {
		BierClearBit(nil, 0) // must not panic
	})

	t.Run("BierAnd with different length slices", func(t *testing.T) {
		a := []byte{0xFF, 0xFF, 0xFF} // 3 bytes
		b := []byte{0x0F, 0xF0}       // 2 bytes — shorter
		res := BierAnd(a, b)
		if len(res) != 2 {
			t.Errorf("result length should be min(3,2)=2, got %d", len(res))
		}
		if res[0] != 0x0F || res[1] != 0xF0 {
			t.Errorf("unexpected result %v", res)
		}
	})

	t.Run("BierAnd both nil/empty returns empty", func(t *testing.T) {
		res := BierAnd(nil, nil)
		if len(res) != 0 {
			t.Errorf("AND of two nils should be empty")
		}
	})

	t.Run("BierAndNot shorter mask", func(t *testing.T) {
		a := []byte{0xFF, 0xFF} // 2 bytes
		b := []byte{0x0F}       // 1 byte — shorter
		res := BierAndNot(a, b)
		// Only first byte gets bits cleared
		if res[0] != 0xF0 {
			t.Errorf("byte 0: expected 0xF0, got %02x", res[0])
		}
		if res[1] != 0xFF {
			t.Errorf("byte 1: expected 0xFF, got %02x", res[1])
		}
	})

	t.Run("BierIsZero on nil is true", func(t *testing.T) {
		if !BierIsZero(nil) {
			t.Error("nil bitstring should be zero")
		}
	})

	t.Run("BierIsZero on empty slice is true", func(t *testing.T) {
		if !BierIsZero([]byte{}) {
			t.Error("empty bitstring should be zero")
		}
	})

	t.Run("BierClone of nil returns nil", func(t *testing.T) {
		if BierClone(nil) != nil {
			t.Error("clone of nil should be nil")
		}
	})

	t.Run("BierClone of empty slice returns empty (not nil)", func(t *testing.T) {
		c := BierClone([]byte{})
		if c == nil {
			t.Error("clone of empty slice should be non-nil")
		}
		if len(c) != 0 {
			t.Error("clone of empty slice should be length 0")
		}
	})

	t.Run("Large bit positions (multi-byte)", func(t *testing.T) {
		var bs []byte
		positions := []int{0, 63, 64, 127, 255}
		for _, pos := range positions {
			bs = BierSetBit(bs, pos)
		}
		for _, pos := range positions {
			if !BierGetBit(bs, pos) {
				t.Errorf("bit %d should be set", pos)
			}
		}
		// Adjacent bits should be clear
		if BierGetBit(bs, 1) {
			t.Error("bit 1 should not be set")
		}
		if BierGetBit(bs, 62) {
			t.Error("bit 62 should not be set")
		}
	})
}

// --- IsBierEnabled / CfgBierIndex ---

func TestBierEnabledConfig(t *testing.T) {
	t.Run("disabled when BierIndex is -1 (default)", func(t *testing.T) {
		restore := setBierIndex(-1)
		defer restore()
		if IsBierEnabled() {
			t.Error("BIER should be disabled when BierIndex=-1")
		}
		if CfgBierIndex() != -1 {
			t.Error("CfgBierIndex should return -1")
		}
	})

	t.Run("enabled when BierIndex is 0", func(t *testing.T) {
		restore := setBierIndex(0)
		defer restore()
		if !IsBierEnabled() {
			t.Error("BIER should be enabled when BierIndex=0")
		}
	})

	t.Run("enabled for large index", func(t *testing.T) {
		restore := setBierIndex(255)
		defer restore()
		if !IsBierEnabled() {
			t.Error("BIER should be enabled when BierIndex=255")
		}
	})
}

// --- BIFT edge cases ---

func TestBiftEdgeCases(t *testing.T) {
	t.Run("GetNeighborEntries on empty BIFT", func(t *testing.T) {
		b := &BiftState{}
		neighbors := b.GetNeighborEntries()
		if len(neighbors) != 0 {
			t.Errorf("empty BIFT should have 0 neighbors, got %d", len(neighbors))
		}
	})

	t.Run("GetNeighborEntries skips entries with no next hop", func(t *testing.T) {
		b := &BiftState{}
		r := enc.Name{enc.NewGenericComponent("r")}
		b.RegisterRouter(r, 0)
		// No UpdateNextHop call — NextHop is 0

		neighbors := b.GetNeighborEntries()
		if len(neighbors) != 0 {
			t.Errorf("router with zero NextHop should not appear in neighbors, got %d", len(neighbors))
		}
	})

	t.Run("GetNeighborEntries skips entries with nil F-BM", func(t *testing.T) {
		b := &BiftState{}
		r := enc.Name{enc.NewGenericComponent("r")}
		b.RegisterRouter(r, 1)
		b.UpdateNextHop(1, 99)
		// RebuildFbm NOT called — Fbm is nil

		neighbors := b.GetNeighborEntries()
		if len(neighbors) != 0 {
			t.Errorf("router with nil Fbm should not appear in neighbors, got %d", len(neighbors))
		}
	})

	t.Run("RebuildFbm on empty BIFT does not panic", func(t *testing.T) {
		b := &BiftState{}
		b.RebuildFbm() // must not panic
	})

	t.Run("BuildBierBitString with empty egress list returns nil", func(t *testing.T) {
		b := &BiftState{}
		bs := b.BuildBierBitString(nil)
		if bs != nil {
			t.Errorf("empty egress list should return nil, got %v", bs)
		}
	})

	t.Run("BuildBierBitString with all unknown routers returns nil", func(t *testing.T) {
		b := &BiftState{}
		unknown := enc.Name{enc.NewGenericComponent("unknown")}
		bs := b.BuildBierBitString([]enc.Name{unknown})
		if bs != nil {
			t.Errorf("all-unknown egress routers should return nil, got %v", bs)
		}
	})

	t.Run("RegisterRouter overwrites existing BFR-ID", func(t *testing.T) {
		b := &BiftState{}
		r := enc.Name{enc.NewGenericComponent("router")}
		b.RegisterRouter(r, 3)
		b.RegisterRouter(r, 7) // re-register same name, different bit

		id, ok := b.GetRouterBfrId(r)
		if !ok {
			t.Fatal("router should exist after re-registration")
		}
		if id != 7 {
			t.Errorf("after re-registration BFR-ID should be 7, got %d", id)
		}
	})

	t.Run("UpdateNextHop on non-existent BFR-ID is a no-op", func(t *testing.T) {
		b := &BiftState{}
		b.UpdateNextHop(99, 100) // must not panic
	})

	t.Run("RebuildFbm groups multiple BFR-IDs per face", func(t *testing.T) {
		b := &BiftState{}
		for i := 0; i < 8; i++ {
			name := enc.Name{enc.NewGenericComponent("r" + string(rune('0'+i)))}
			b.RegisterRouter(name, i)
			b.UpdateNextHop(i, 555) // all share one face
		}
		b.RebuildFbm()

		neighbors := b.GetNeighborEntries()
		if len(neighbors) != 1 {
			t.Fatalf("expected 1 neighbor (face 555), got %d", len(neighbors))
		}
		fbm := neighbors[0].Fbm
		for i := 0; i < 8; i++ {
			if !BierGetBit(fbm, i) {
				t.Errorf("F-BM for face 555 should have bit %d set", i)
			}
		}
	})

	t.Run("Multiple calls to BuildFromFibPet do not corrupt state", func(t *testing.T) {
		// Calling BuildFromFibPet requires FibStrategyTable to be initialized.
		// Use table.Initialize() to set it up with the default config.
		table.Initialize()

		b := &BiftState{}
		r := enc.Name{enc.NewGenericComponent("r")}
		b.RegisterRouter(r, 0)
		b.BuildFromFibPet() // FIB empty → no next hops resolved, no panic
		b.BuildFromFibPet() // second call also safe
	})
}

// --- Concurrent access ---

func TestBiftConcurrency(t *testing.T) {
	b := &BiftState{}
	var wg sync.WaitGroup
	const goroutines = 20

	// Concurrent RegisterRouter
	wg.Add(goroutines)
	for i := 0; i < goroutines; i++ {
		go func(i int) {
			defer wg.Done()
			name := enc.Name{enc.NewGenericComponent("cr" + string(rune('A'+i%26)))}
			b.RegisterRouter(name, i%64)
		}(i)
	}
	wg.Wait()

	// Concurrent GetRouterBfrId while UpdateNextHop runs
	wg.Add(goroutines * 2)
	for i := 0; i < goroutines; i++ {
		go func(i int) {
			defer wg.Done()
			b.UpdateNextHop(i%64, uint64(100+i))
		}(i)
		go func(i int) {
			defer wg.Done()
			name := enc.Name{enc.NewGenericComponent("cr" + string(rune('A'+i%26)))}
			b.GetRouterBfrId(name)
		}(i)
	}
	wg.Wait()

	// Concurrent RebuildFbm + GetNeighborEntries
	wg.Add(goroutines * 2)
	for i := 0; i < goroutines; i++ {
		go func() {
			defer wg.Done()
			b.RebuildFbm()
		}()
		go func() {
			defer wg.Done()
			b.GetNeighborEntries()
		}()
	}
	wg.Wait()
}


func TestBiftBuildBierBitStringMixed(t *testing.T) {
	b := &BiftState{}
	known := enc.Name{enc.NewGenericComponent("known")}
	unknown := enc.Name{enc.NewGenericComponent("unknown")}

	b.RegisterRouter(known, 3)
	egressRouters := []enc.Name{known, unknown}
	bs := b.BuildBierBitString(egressRouters)

	// Only bit 3 should be set (unknown skipped)
	if !BierGetBit(bs, 3) {
		t.Error("bit 3 should be set for known router")
	}
	if BierGetBit(bs, 0) || BierGetBit(bs, 1) || BierGetBit(bs, 2) {
		t.Error("only bit 3 should be set")
	}
}

func TestBierAndNotDoesNotModifyInputs(t *testing.T) {
	a := []byte{0xFF, 0xFF}
	b := []byte{0x0F, 0xF0}
	aCopy := BierClone(a)
	bCopy := BierClone(b)

	BierAndNot(a, b)

	for i := range a {
		if a[i] != aCopy[i] {
			t.Errorf("BierAndNot mutated a at byte %d", i)
		}
	}
	for i := range b {
		if b[i] != bCopy[i] {
			t.Errorf("BierAndNot mutated b at byte %d", i)
		}
	}
}

func TestBierAndDoesNotModifyInputs(t *testing.T) {
	a := []byte{0xAA, 0xBB}
	b := []byte{0xCC, 0xDD}
	aCopy := BierClone(a)
	bCopy := BierClone(b)

	BierAnd(a, b)

	for i := range a {
		if a[i] != aCopy[i] {
			t.Errorf("BierAnd mutated a at byte %d", i)
		}
	}
	for i := range b {
		if b[i] != bCopy[i] {
			t.Errorf("BierAnd mutated b at byte %d", i)
		}
	}
}
