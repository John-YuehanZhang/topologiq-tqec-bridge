# A small bridge from topologiq to tqec

**Start with [`bridge_demo.ipynb`](bridge_demo.ipynb)** — it walks one
circuit through the whole chain, one step per cell, with the 3D
diagrams before and after the rewrite, and saves every intermediate
file under `data/` and `figures/`.

This repository holds two small fixes that let circuits compiled by
[topologiq](https://github.com/tqec/topologiq) run all the way through
[tqec](https://github.com/tqec/tqec) into stim circuits.  With them,
34 of the 45 Clifford programs in our benchmark suite compile end to
end and pass the p=0 checks (no detector fires, every observable is
constant).  Neither tool's source code is modified: both fixes act on
the data between the two tools.

## What breaks without the bridge

**1. Entries without a position.**  When the input circuit has qubits
that never interact (for example the zero bits of a Bernstein-Vazirani
secret), the ZX graph has more than one connected component.
topologiq's default traversal (`bfs-cross`) only visits the first
component, leaves the rest without coordinates, still reports SUCCESS,
and writes them into the `.bgraph` file as
`1;None;None;None;;in_1;`.  `BlockGraph.from_bgraph` then fails with
`Error parsing cubes` (the BGRAPH spec asks for integer positions).

*Fix: drop these lines before reading the file (one filter).  The
dropped entries are the untouched qubits; they carry no geometry.
Alternative: `graph_traverse_mode="bfs-rows"` visits all components
and avoids the problem for most circuits, but can fail with
`No path found` on others.*

**2. Hadamard pipes on junction cubes.**  topologiq turns H gates into
Hadamard pipes (a pipe whose wall colors flip along the way).  Its
router often places such a pipe directly against a junction cube
(XXZ/ZZX).  tqec does not compile that combination yet:
`fixed_boundary` rejects any spatial Hadamard pipe that touches a
junction cube, and `fixed_bulk` lacks the left/right Hadamard arm
(see [tqec#631](https://github.com/tqec/tqec/issues/631),
[tqec#838](https://github.com/tqec/tqec/issues/838)).
Plain spatial Hadamard pipes between two regular cubes ARE
implemented in `fixed_boundary` — the gap is only the junction case.

*Fix (`hadamard_rewrite.py`): stretch the graph by one unit along the
pipe axis, insert a regular cube with matching colors into every pipe
that crosses the cut, and leave the color flip on the segment whose
both ends are regular cubes.  Inserting a cube only makes the tube one
unit longer, and the color-flip wall can sit anywhere along the tube,
so the computation does not change — the structure just moves into
the part of the vocabulary tqec already compiles.  All compiled
results below go through `fixed_boundary` after this rewrite.*

```
before:   [regular cube] ==H pipe== [junction cube]     <- not implemented
after:    [regular cube] ==H pipe== [inserted cube] --plain pipe-- [junction cube]
```

## How to reproduce

```bash
git clone https://github.com/John-YuehanZhang/topologiq-tqec-bridge.git
cd topologiq-tqec-bridge
```
then:

```bash
python -m venv venv && source venv/bin/activate
pip install "git+https://github.com/tqec/topologiq.git" "git+https://github.com/tqec/tqec.git"
python reproduce.py            # built-in bv_6 example (15 gates)
```

Expected output (tested in a fresh environment):

```
topologiq wrote .../output_bgraph/bv_6.bgraph
bv_6.bgraph: 1 rewrite round(s)
  rewritten graph: 28 cubes, 27 pipes; validate OK
  COMPILES via fixed_boundary (fill #0): 337q, 4 obs, p=0 silent=True, deterministic obs 4/4
DONE
```

`python reproduce.py your.qasm` runs any other circuit (unitary part —
drop `measure`/`creg` lines).  `hadamard_rewrite.py <file>.bgraph`
alone runs just the bridge half: it drops the positionless entries,
reads the file with tqec's own `BlockGraph.from_bgraph`, applies the
rewrite, fills the ports, compiles, and samples at p=0.

## Results over our benchmark suite

See `RESULTS_TABLE.md` for the per-program list (35 compiled rows; 34
are structurally valid — one, bv_n70, is excluded because topologiq's
router left most of its graph unplaced).  Failures outside the table
and their reasons:

- Y states (S gates / iswap): topologiq emits Y half-cubes with
  spatial pipes, or its own `Yi`/`XZ*`/`ZXt` cube kinds; tqec's
  compiler has no Y cube yet.
- graph states: hit another not-implemented corner even after the
  rewrite.
- `MultipleOperationsOnSameQubitError` on three programs
  (grover_n2, hs4_n4, ghz_16_mixed): a tqec moment-scheduling issue.
- (the two 255+ qubit programs are slow, not impossible: topologiq's
  router needs ~45 minutes each, and both then compile cleanly.)

## Cost of the rewrite (and who should pay it)

The rewrite adds cubes.  These extra cubes are the price of our
workaround, **not** part of topologiq's own output, so any volume or
error-rate comparison should book them separately.  Once tqec
implements the junction Hadamard case natively, this cost disappears.

Measured over the 31 compiled programs of our comparison set:

- 15 of 31 programs need **zero** added cubes (their graphs never put
  a Hadamard pipe on a junction);
- overall overhead: 483 added cubes on top of 4569 original ones
  (**+10.6%**);
- the H-heavy families pay the most: dj_64 +126 cubes (+33%),
  bv_64 +64, dj_32 +62, bv_n19/bv_n30 +36 each.

Note the direction of the bias: the added cubes also add noise
locations, so the compiled topologiq circuits perform slightly
*worse* than the tool's own structures would.  Numbers measured
through this bridge are a lower bound on topologiq's quality.

## Caveats

- The port fills are the ones `fill_ports_for_minimal_simulation()`
  picks, so each compiled circuit is *a* valid computation on the
  structure, not yet the exact benchmark program; matching the fills
  to the program is the next step and is what our comparison harness
  does.
- Two programs (steane_encode, teleport_8) compile but carry one
  detector that flips in ~50% of p=0 shots — reproducible with
  unmodified tools, worth an upstream look.
