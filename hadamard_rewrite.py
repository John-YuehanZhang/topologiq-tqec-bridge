"""Compatibility rewrite: detach Hadamard pipes from spatial-junction cubes.

A spatial H pipe touching a spatial cube (XXZ/ZZX) is unimplemented in
both tqec conventions.  Fix: stretch the graph by one unit along the
pipe axis at the junction side, insert a regular cube in the gap, and
leave the H on the segment whose both ends are regular (the domain
wall slides freely along the tube, so semantics are unchanged).
Every other pipe crossing the cut plane is likewise extended through
an inserted cube of matching colors.
"""
import sys
from pathlib import Path

from tqec import BlockGraph, compile_block_graph
from tqec.computation.cube import ZXCube, Port
from tqec.computation.pipe import PipeKind
from tqec.utils.position import Position3D

AXIS = {0: "x", 1: "y", 2: "z"}


def load(clean_text):
    g = BlockGraph.from_bgraph(clean_text)
    cubes = {}                    # pos -> (kind_str_or_PORT, label)
    for c in g.cubes:
        if c.is_port:
            cubes[c.position] = ("PORT", c.label)
        else:
            cubes[c.position] = (str(c.kind), c.label)
    pipes = []                    # (u_pos, v_pos, kind_str)
    for p in g.pipes:
        pipes.append((p.u.position, p.v.position, str(p.kind)))
    return cubes, pipes


def is_spatial_cube(kind):
    return kind not in ("PORT",) and len(kind) == 3 and kind[0] == kind[1]


def pipe_axis(kind):
    return kind.upper().index("O")


def valid_kinds(x=None, y=None, z=None):
    out = []
    for a in "XZ":
        for b in "XZ":
            for c in "XZ":
                k = a + b + c
                if len(set(k)) == 1:
                    continue
                if (x and a != x) or (y and b != y) or (z and c != z):
                    continue
                out.append(k)
    return out


def stretch_and_fix(cubes, pipes):
    """One rewrite round: fix the first offending H pipe; return None if clean."""
    for i, (u, v, kind) in enumerate(pipes):
        if not kind.endswith("H") or pipe_axis(kind) == 2:
            continue                      # temporal H is fine
        su = is_spatial_cube(cubes[u][0])
        sv = is_spatial_cube(cubes[v][0])
        if not (su or sv):
            continue
        ax = pipe_axis(kind)
        # cut just below the higher endpoint along the pipe axis
        hi = u if u.as_tuple()[ax] > v.as_tuple()[ax] else v
        cut = hi.as_tuple()[ax]

        def shift(pos):
            t = list(pos.as_tuple())
            if t[ax] >= cut:
                t[ax] += 1
            return Position3D(*t)

        new_cubes = {shift(p): kv for p, kv in cubes.items()}
        new_pipes = []
        for (a, b, k) in pipes:
            a2, b2 = shift(a), shift(b)
            gap = abs(a2.as_tuple()[pipe_axis(k)] - b2.as_tuple()[pipe_axis(k)])
            if gap == 1:
                new_pipes.append((a2, b2, k))
                continue
            # pipe crosses the cut: insert a cube in the gap
            lo, hi2 = (a2, b2) if a2.as_tuple()[pipe_axis(k)] < b2.as_tuple()[pipe_axis(k)] else (b2, a2)
            t = list(lo.as_tuple()); t[pipe_axis(k)] += 1
            mid = Position3D(*t)
            plain = k[:3]
            flip = "".join({"X": "Z", "Z": "X", "O": "O"}[c] for c in plain)

            def mid_kind(letters):
                fixed = {AXIS[d]: letters[d] for d in range(3)
                         if d != pipe_axis(k)}
                cands = valid_kinds(**fixed)
                cands.sort(key=lambda kk: kk[0] == kk[1])   # 非枢纽优先
                return cands[0]

            if k.endswith("H"):
                # keep H on the segment away from any spatial-cube endpoint;
                # the mid cube and far segment carry the flipped colors
                lo_sp = is_spatial_cube(new_cubes[lo][0])
                if lo_sp:
                    # H on mid--hi2: mid keeps unflipped colors
                    new_cubes[mid] = (mid_kind(plain), "")
                    new_pipes.append((lo, mid, plain))
                    new_pipes.append((mid, hi2, plain + "H"))
                else:
                    # H on lo--mid: mid takes flipped colors
                    new_cubes[mid] = (mid_kind(flip), "")
                    new_pipes.append((lo, mid, plain + "H"))
                    new_pipes.append((mid, hi2, flip))
            else:
                new_cubes[mid] = (mid_kind(plain), "")
                new_pipes.append((lo, mid, plain))
                new_pipes.append((mid, hi2, plain))
        return new_cubes, new_pipes
    return None


def to_blockgraph(cubes, pipes, name="rewritten"):
    g = BlockGraph(name)
    for p, (kind, label) in cubes.items():
        if kind == "PORT":
            g.add_cube(p, "PORT", label=label)
        else:
            g.add_cube(p, kind, label=label)
    for (a, b, k) in pipes:
        g.add_pipe(a, b, PipeKind.from_str(k))
    return g


def try_compile(g):
    from tqec.compile.convention import FIXED_BOUNDARY_CONVENTION, FIXED_BULK_CONVENTION
    fgs = g.fill_ports_for_minimal_simulation()
    for nm, conv in (("fixed_boundary", FIXED_BOUNDARY_CONVENTION),
                     ("fixed_bulk", FIXED_BULK_CONVENTION)):
        for n, fg in enumerate(fgs):
            fgraph = fg.graph if hasattr(fg, "graph") else fg
            try:
                circ = compile_block_graph(fgraph, observables="auto",
                                           convention=conv).generate_stim_circuit(k=1)
                return nm, n, circ
            except Exception:
                continue
    return None


def main(path):
    clean = "\n".join(l for l in Path(path).read_text().splitlines() if "None" not in l)
    cubes, pipes = load(clean)
    rounds = 0
    while rounds < 8:
        step = stretch_and_fix(cubes, pipes)
        if step is None:
            break
        cubes, pipes = step
        rounds += 1
    print(f"{path}: {rounds} rewrite round(s)")
    g = to_blockgraph(cubes, pipes)
    g.validate()
    print(f"  rewritten graph: {g.num_cubes} cubes, {g.num_pipes} pipes; validate OK")
    r = try_compile(g)
    if r is None:
        print("  still does not compile")
        return None
    nm, n, circ = r
    det, obs = circ.compile_detector_sampler(seed=3).sample(1024, separate_observables=True)
    ndet = sum(1 for k in range(obs.shape[1]) if bool((obs[:, k] == obs[0, k]).all()))
    print(f"  COMPILES via {nm} (fill #{n}): {circ.num_qubits}q, "
          f"{circ.num_observables} obs, p=0 silent={not det.any()}, "
          f"deterministic obs {ndet}/{obs.shape[1]}")
    return circ


if __name__ == "__main__":
    main(sys.argv[1])
