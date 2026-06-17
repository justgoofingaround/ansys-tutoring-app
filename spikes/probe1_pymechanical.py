"""
Probe 1 — Can we read authoritative MODEL STATE from Ansys Mechanical via Python?

THROWAWAY SPIKE CODE. This answers the most important open question in the plan:
"what can we verify per app?". Mechanical is expected to be the STRONGEST path
(PyMechanical / gRPC). If this works, model-state verification (the heart of
'authoritative state verification') is real.

WHAT IT DOES:
  Path A (preferred): connect to an ALREADY-RUNNING Mechanical that exposes a
    gRPC server, and run a tiny read-only script that lists analyses and their
    boundary conditions.
  Path B (fallback proof-of-life): if you can't connect to the GUI instance,
    uncomment LAUNCH_FALLBACK to launch a fresh headless Mechanical and confirm
    the library works at all. (Different from reading the GUI's live model, but
    proves PyMechanical is installed and functional.)

PASS if Path A prints the analyses/BC list of the model you have open.

KEY UNKNOWN (this probe resolves it): a Mechanical opened from Workbench's GUI
only exposes gRPC if its remote/scripting server is enabled. If Path A can't
connect, that's the finding — note HOW you have to enable it (e.g. launch flag,
in-app scripting console) for the real bridge.

SETUP:
  pip install ansys-mechanical-core
  Open Mechanical from the Workbench Model cell, with a model that has at least
  one boundary condition, then:   python probe1_pymechanical.py
"""

import sys

try:
    from ansys.mechanical.core import Mechanical
except ImportError:
    sys.exit("ansys-mechanical-core not installed.  pip install ansys-mechanical-core")

# Default gRPC endpoint. Adjust the port if your Mechanical reports a different one.
IP = "127.0.0.1"
PORT = 10000

# Read-only script executed INSIDE Mechanical's scripting API (ExtAPI / DataModel).
# Returns a printable summary; does not modify the model.
READ_MODEL_STATE = r"""
lines = []
try:
    model = ExtAPI.DataModel.Project.Model
    analyses = model.Analyses
    lines.append("geometry parts: %d" % len(model.Geometry.Children))
    for a in analyses:
        bc_names = []
        for child in a.Children:
            bc_names.append(child.Name)
        lines.append("analysis '%s': %s" % (a.Name, ", ".join(bc_names) or "(no children)"))
    if not analyses:
        lines.append("no analyses in the model")
except Exception as e:
    lines.append("error reading model: %s" % e)
"\n".join(lines)
"""


def path_a_connect():
    print(f"Path A: connecting to running Mechanical at {IP}:{PORT} ...")
    mech = Mechanical(ip=IP, port=PORT)        # raises if nothing is listening
    print("Connected. Mechanical reports:")
    try:
        print(" ", mech.version)
    except Exception:
        pass
    print("\n=== model state ===")
    out = mech.run_python_script(READ_MODEL_STATE)
    print(out)
    print("\nPASS: read authoritative model state over gRPC.")
    mech.exit(force=False)  # detach; do not close the user's GUI session


# --- Path B fallback (uncomment to use) ---------------------------------------
# def path_b_launch():
#     from ansys.mechanical.core import launch_mechanical
#     print("Path B: launching a fresh headless Mechanical (proof-of-life only)...")
#     mech = launch_mechanical(batch=True)
#     print("Launched:", mech.version)
#     print(mech.run_python_script('"PyMechanical works: " + str(2 + 2)'))
#     mech.exit(force=True)
#     print("PASS (library works). NOTE: this is NOT the live GUI model.")


def main():
    try:
        path_a_connect()
    except Exception as e:
        print(f"\nPath A failed: {e}\n")
        print("This is the key finding. The GUI Mechanical likely isn't exposing")
        print("a gRPC server. To enable it, investigate one of:")
        print("  - launching Mechanical with its remote/scripting server on")
        print("  - the port it actually advertises (edit PORT above)")
        print("  - using the in-app Scripting console to confirm ExtAPI access")
        print("\nTo at least confirm PyMechanical installs/runs, uncomment Path B.")
        sys.exit(1)


if __name__ == "__main__":
    main()
