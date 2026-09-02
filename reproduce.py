"""One-command reproduction: QASM -> topologiq -> bridge -> tqec -> stim.

Usage:
    python reproduce.py               # built-in bv_6 example (15 gates)
    python reproduce.py my.qasm       # your own circuit (unitary part)

Needs one python environment with both tools:
    pip install "git+https://github.com/tqec/topologiq.git" \
                "git+https://github.com/tqec/tqec.git"
and hadamard_rewrite.py from this gist in the same folder.
"""
import contextlib
import io
import pathlib
import sys
import tempfile

import matplotlib
matplotlib.use("Agg")

BV6 = """OPENQASM 2.0;
include "qelib1.inc";
qreg q[6];
x q[5];
h q[0];
h q[1];
h q[2];
h q[3];
h q[4];
h q[5];
cx q[0],q[5];
cx q[2],q[5];
cx q[4],q[5];
h q[0];
h q[1];
h q[2];
h q[3];
h q[4];
"""


def main():
    if len(sys.argv) > 1:
        qasm_path = pathlib.Path(sys.argv[1])
        name = qasm_path.stem
    else:
        tmp = pathlib.Path(tempfile.mkdtemp())
        qasm_path = tmp / "bv_6.qasm"
        qasm_path.write_text(BV6)
        name = "bv_6"

    outdir = pathlib.Path("./output_bgraph").resolve()
    outdir.mkdir(exist_ok=True)

    # step 1: topologiq  (QASM -> .bgraph)
    from topologiq.core.graph_manager import graph_manager as gm
    gm.BGRAPH_DIR = outdir                     # redirect its output here
    from topologiq.input.zx_manager import ZXGraphManager
    zxm = ZXGraphManager()
    aug = zxm.add_graph_from_qasm(path_to_qasm_file=qasm_path, graph_key=name)
    with contextlib.redirect_stdout(io.StringIO()):
        mgr = gm.BlockGraphManager(aug, debug=0, seed=0)
        mgr.build()
        mgr.write_bgraph(name)
    f = outdir / f"{name}.bgraph"
    assert f.exists(), "topologiq did not write a bgraph"
    print(f"topologiq wrote {f}")

    # step 2: bridge + tqec compile + p=0 check
    sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
    import hadamard_rewrite as hr
    circ = hr.main(str(f))
    print("DONE" if circ is not None else "FAILED (see messages above)")


if __name__ == "__main__":
    main()
