import json
import os
import sys
from importlib import metadata


def versions() -> dict:
    import OCP

    ocp = str(getattr(OCP, "__version__", "unknown"))
    parts = ocp.split(".")
    occt = ".".join(parts[:3]) if len(parts) >= 3 else ocp
    try:
        builder = metadata.version("build123d")
    except metadata.PackageNotFoundError:
        builder = "unknown"
    return {"occt": occt, "ocp": ocp, "build123d": builder, "python": sys.version.split()[0]}


def hello(_params: dict) -> dict:
    try:
        out = versions()
    except Exception as err:
        raise RuntimeError(f"The OpenCascade bindings could not be loaded ({err}).") from err
    out["units"] = "mm"
    out["methods"] = sorted(METHODS)
    out["protocol"] = 2
    return out


METHODS = {"hello": hello}

OUT = sys.stdout


def isolate_stdout() -> None:
    global OUT
    try:
        saved = os.dup(1)
        OUT = os.fdopen(saved, "w", encoding="utf-8", buffering=1)
        os.dup2(2, 1)
    except OSError:
        OUT = sys.stdout


def load_operations() -> None:
    try:
        from OCP.Message import Message

        printers = Message.DefaultMessenger_s().Printers()
        for printer in list(printers):
            Message.DefaultMessenger_s().RemovePrinter(printer)
    except Exception:
        pass
    try:
        import kernel_io
        import kernel_ops
        import kernel_props
    except Exception as err:
        failure = str(err)

        def unavailable(_params):
            raise RuntimeError("The modelling operations could not be loaded (%s)." % failure)

        METHODS["primitive"] = unavailable
        return
    for module in (kernel_ops, kernel_io, kernel_props):
        METHODS.update(module.METHODS)
    try:
        import kernel_feat

        METHODS.update(kernel_feat.METHODS)
        kernel_feat.load_plugins()
        METHODS.update(kernel_feat.METHODS)
    except Exception as err:
        failure0 = str(err)

        def feat_unavailable(_params):
            raise RuntimeError("The part feature operations could not be loaded (%s)." % failure0)

        for name in ("feat_extrude", "feat_revolve", "feat_signatures", "feat_topology", "feat_rays"):
            METHODS.setdefault(name, feat_unavailable)
    try:
        import kernel_bodies

        METHODS.update(kernel_bodies.METHODS)
    except Exception as err:
        failure = str(err)

        def bodies_unavailable(_params):
            raise RuntimeError("The multibody operations could not be loaded (%s)." % failure)

        for name in ("combine", "split", "geometry", "body_props"):
            METHODS.setdefault(name, bodies_unavailable)
    try:
        import kernel_features2

        METHODS.update(kernel_features2.METHODS)
    except Exception as err:
        failure2 = str(err)

        def features2_unavailable(_params):
            raise RuntimeError("The dress-up and pattern operations could not be loaded (%s)." % failure2)

        for name in ("feature_fillet", "feature_chamfer", "feature_shell", "feature_draft", "feature_pattern", "feature_mirror", "feature_precheck"):
            METHODS.setdefault(name, features2_unavailable)
    try:
        import kernel_shapes

        METHODS.update(kernel_shapes.METHODS)
    except Exception as err:
        failure3 = str(err)

        def shapes_unavailable(_params):
            raise RuntimeError("The sweep, loft and hole operations could not be loaded (%s)." % failure3)

        for name in ("sweep", "sweep_preview", "loft", "boundary_solid", "rib", "hole"):
            METHODS.setdefault(name, shapes_unavailable)
    try:
        import kernel_curves

        METHODS.update(kernel_curves.METHODS)
    except Exception as err:
        failure4 = str(err)

        def curves_unavailable(_params):
            raise RuntimeError("The curve operations could not be loaded (%s)." % failure4)

        for name in ("curve_make", "curve_interpolate", "curve_approximate", "curve_refit", "curve_rebuild", "curve_degree", "curve_continuity", "curve_offset", "curve_extend"):
            METHODS.setdefault(name, curves_unavailable)
    try:
        import kernel_diag
        import kernel_match
        import kernel_surf

        for module in (kernel_surf, kernel_match, kernel_diag):
            METHODS.update(module.METHODS)
    except Exception as err:
        failure5 = str(err)

        def surfaces_unavailable(_params):
            raise RuntimeError("The surface operations could not be loaded (%s)." % failure5)

        for name in ("surf_loft", "surf_sweep", "surf_network", "surf_patch", "surf_extrude", "surf_revolve", "surf_planar", "surf_edge", "surf_extend", "surf_offset", "surf_split", "surf_join", "surf_continuity", "surf_blend", "surf_match", "bool_diag", "fillet_edge", "chamfer_edge"):
            METHODS.setdefault(name, surfaces_unavailable)
    try:
        import kernel_views

        METHODS.update(kernel_views.METHODS)
    except Exception as err:
        failure6 = str(err)

        def views_unavailable(_params):
            raise RuntimeError("The drawing view operations could not be loaded (%s)." % failure6)

        METHODS.setdefault("view_build", views_unavailable)
    try:
        import kernel_analysis

        METHODS.update(kernel_analysis.METHODS)
    except Exception as err:
        failure6 = str(err)

        def analysis_unavailable(_params):
            raise RuntimeError("The analysis operations could not be loaded (%s)." % failure6)

        for name in ("an_shape_data", "an_deviation", "an_comb", "an_affine", "an_snap"):
            METHODS.setdefault(name, analysis_unavailable)
    try:
        import kernel_3dm

        METHODS.update(kernel_3dm.METHODS)
    except Exception as err:
        failure7 = str(err)

        def threedm_unavailable(_params):
            raise RuntimeError("The 3DM operations could not be loaded (%s)." % failure7)

        for name in ("threedm_info", "threedm_read", "threedm_write", "threedm_compare", "threedm_curve_compare", "threedm_verify"):
            METHODS.setdefault(name, threedm_unavailable)
    try:
        import kernel_asm

        METHODS.update(kernel_asm.METHODS)
    except Exception as err:
        failure8 = str(err)

        def assembly_unavailable(_params):
            raise RuntimeError("The assembly operations could not be loaded (%s)." % failure8)

        for name in ("asm_interference", "asm_blocking"):
            METHODS.setdefault(name, assembly_unavailable)
    try:
        import kernel_proxy

        METHODS.update(kernel_proxy.METHODS)
    except Exception as err:
        failure_proxy = str(err)

        def proxy_unavailable(_params):
            raise RuntimeError("The collision proxy operation could not be loaded (%s)." % failure_proxy)

        METHODS.setdefault("asm_proxy", proxy_unavailable)
    try:
        import kernel_unfold

        METHODS.update(kernel_unfold.METHODS)
    except Exception as err:
        failure9 = str(err)

        def unfold_unavailable(_params):
            raise RuntimeError("The flat pattern operations could not be loaded (%s)." % failure9)

        METHODS.setdefault("unfold_solid", unfold_unavailable)
    try:
        import kernel_sheet

        METHODS.update(kernel_sheet.METHODS)
    except Exception as err:
        failure11 = str(err)

        def sheet_unavailable(_params):
            raise RuntimeError("The sheet metal operations could not be loaded (%s)." % failure11)

        for name in ("sm_base_flange", "sm_edge_flange", "sm_miter_flange", "sm_hem", "sm_jog", "sm_sketched_bend", "sm_bend_relief", "sm_corner_relief", "sm_convert", "sm_analyze", "sm_verify"):
            METHODS.setdefault(name, sheet_unavailable)
    try:
        import kernel_subd

        METHODS.update(kernel_subd.METHODS)
    except Exception as err:
        failure41 = str(err)

        def subd_unavailable(_params):
            raise RuntimeError("The form conversion operations could not be loaded (%s)." % failure41)

        METHODS.setdefault("subd_brep", subd_unavailable)
    try:
        import kernel_plastic

        METHODS.update(kernel_plastic.METHODS)
    except Exception as err:
        failure31 = str(err)

        def plastic_unavailable(_params):
            raise RuntimeError("The plastic part operations could not be loaded (%s)." % failure31)

        for name in ("pl_boss", "pl_rib", "pl_snap_hook", "pl_lip", "pl_groove", "pl_wall", "pl_inspect"):
            METHODS.setdefault(name, plastic_unavailable)
    try:
        import kernel_graph

        METHODS.update(kernel_graph.METHODS)
    except Exception as err:
        failure10 = str(err)

        def graph_unavailable(_params):
            raise RuntimeError("The graph geometry operations could not be loaded (%s)." % failure10)

        for name in ("graph_batch", "graph_preview", "graph_alive"):
            METHODS.setdefault(name, graph_unavailable)
    try:
        import kernel_xde

        METHODS.update(kernel_xde.METHODS)
    except Exception as err:
        failure25 = str(err)

        def xde_unavailable(_params):
            raise RuntimeError("The STEP and IGES exchange operations could not be loaded (%s)." % failure25)

        for name in ("xde_read", "xde_write", "pmi_measure", "pmi_anchors", "pmi_features"):
            METHODS.setdefault(name, xde_unavailable)
    try:
        import kernel_meshbrep

        METHODS.update(kernel_meshbrep.METHODS)
    except Exception as err:
        failure26 = str(err)

        def meshbrep_unavailable(_params):
            raise RuntimeError("The mesh to solid operation could not be loaded (%s)." % failure26)

        METHODS.setdefault("mesh_to_brep", meshbrep_unavailable)


def reply(payload: dict) -> None:
    OUT.write(json.dumps(payload) + "\n")
    OUT.flush()


def serve() -> int:
    isolate_stdout()
    load_operations()
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            request = json.loads(line)
            ident = request.get("id")
            method = request.get("method")
        except (ValueError, AttributeError):
            reply({"id": None, "error": {"message": "The request is not a JSON object."}})
            continue
        if method == "shutdown":
            reply({"id": ident, "result": {"ok": True}})
            return 0
        handler = METHODS.get(method)
        if handler is None:
            reply({"id": ident, "error": {"message": f"Unknown method {method}."}})
            continue
        try:
            reply({"id": ident, "result": handler(request.get("params") or {})})
        except Exception as err:
            reply({"id": ident, "error": {"message": str(err)}})
    return 0


if __name__ == "__main__":
    sys.exit(serve())
