from typing import Any, Optional

from fastapi import APIRouter, HTTPException
from fastapi.responses import Response
from pydantic import BaseModel

from app.doc import layouts as L
from app.doc import papers
from app.doc.service import DocumentFault, service
from app.output import devices, jobs, plot, plotstyle, request as R, styleops

router = APIRouter(tags=["plot"])


class PlotBody(BaseModel):
    request: dict[str, Any] = {}
    kind: Optional[str] = None
    wait: bool = True


class StyleBody(BaseModel):
    action: str
    args: dict[str, Any] = {}


def _doc(doc_id: str):
    try:
        return service.get(doc_id)
    except DocumentFault as err:
        raise HTTPException(err.status, err.message)


@router.get("/plot/devices")
def list_devices() -> dict:
    return {"devices": devices.listing()}


@router.get("/plot/devices/{name}")
def get_device(name: str) -> dict:
    dev = devices.find(name)
    if dev is None:
        raise HTTPException(404, "No such device.")
    return {**devices.summary(dev), "paperList": dev["papers"]}


@router.post("/plot/devices")
def add_device(body: dict[str, Any]) -> dict:
    try:
        path = devices.save_device(body)
    except devices.DeviceError as err:
        raise HTTPException(400, str(err))
    return {"path": path, "devices": devices.listing()}


@router.get("/plot/papers")
def list_papers() -> dict:
    return {"papers": papers.listing(), "maxSide": papers.MAX_SIDE_MM}


@router.get("/docs/{doc_id}/plot/defaults")
def plot_defaults(doc_id: str, layout: str = "Model", device: str = "") -> dict:
    doc = _doc(doc_id)
    with doc.lock:
        try:
            req = R.clean({"layout": layout, "device": device} if device else {"layout": layout})
            dev = R.device_for(req)
            spec = R.resolve_sheet(doc.drawing, req, layout, dev)
        except R.PlotError as err:
            raise HTTPException(400, str(err))
        ps = spec["ps"]
        return {"layout": spec["name"], "model": spec["model"], "device": dev["name"], "output": dev["output"], "resolution": dev["resolution"], "paper": spec["paper"], "width": spec["width"], "height": spec["height"], "landscape": spec["landscape"], "margins": spec["margins"], "printable": spec["printable"], "area": spec["area"], "window": spec["window"], "fit": spec["fit"], "scale": spec["scale"], "scaleText": L.scale_text_of(spec["scale"]) if spec["scale"] else "1:1", "center": spec["center"], "offset": spec["offset"], "lineweights": spec["lineweights"], "transparency": spec["transparency"], "displayStyles": spec["display_styles"], "styleTable": spec["style_table"], "unit": "mm" if spec["unit"] == 1.0 else "in", "layouts": ["Model"] + L.names(doc.drawing), "pageSetup": ps}


@router.post("/docs/{doc_id}/plot")
def start_plot(doc_id: str, body: PlotBody) -> dict:
    doc = _doc(doc_id)
    kind = (body.kind or "plot").lower()
    if kind not in ("plot", "pdf", "png", "svg"):
        raise HTTPException(400, "The kind is plot, pdf, png or svg.")
    job = jobs.submit(doc, doc_id, kind, body.request, wait=body.wait)
    return jobs.get(job.id).view()


@router.post("/docs/{doc_id}/plot/preview")
def plot_preview(doc_id: str, body: dict[str, Any]) -> Response:
    doc = _doc(doc_id)
    try:
        res = plot.preview(doc, body)
    except R.PlotError as err:
        raise HTTPException(400, str(err))
    except Exception as err:
        raise HTTPException(400, "The preview failed: %s" % err)
    hdr = {"X-Preview-Width": str(res["width"]), "X-Preview-Height": str(res["height"]), "X-Preview-Dpi": "%.2f" % res["dpi"], "X-Sheet-Name": res["sheet"]["name"], "X-Sheet-Mm": "%.3f,%.3f" % (res["sheet"]["width"], res["sheet"]["height"]), "X-Printable-Mm": ",".join("%.3f" % v for v in res["sheet"]["printable"])}
    return Response(content=res["data"], media_type="image/png", headers=hdr)


@router.get("/plot/jobs")
def list_jobs(doc: Optional[str] = None) -> dict:
    return {"jobs": jobs.listing(doc)}


@router.get("/plot/jobs/{job_id}")
def get_job(job_id: str) -> dict:
    job = jobs.get(job_id)
    if job is None:
        raise HTTPException(404, "No such plot job.")
    return job.view()


@router.get("/plot/jobs/{job_id}/result")
def job_result(job_id: str) -> Response:
    job = jobs.get(job_id)
    if job is None:
        raise HTTPException(404, "No such plot job.")
    if job.state in ("queued", "running"):
        raise HTTPException(409, "The plot is still running.")
    if job.result is None:
        raise HTTPException(404, job.message or "The plot has no result.")
    r = job.result
    return Response(content=r["data"], media_type=r["mime"], headers={"Content-Disposition": 'attachment; filename="plot.%s"' % r["output"]})


@router.get("/docs/{doc_id}/plot/styles")
def list_styles(doc_id: str) -> dict:
    doc = _doc(doc_id)
    with doc.lock:
        return styleops.apply(doc, "list", {})


@router.get("/docs/{doc_id}/plot/styles/{name}")
def get_style(doc_id: str, name: str) -> dict:
    doc = _doc(doc_id)
    with doc.lock:
        try:
            return styleops.apply(doc, "get", {"name": name})
        except plotstyle.StyleError as err:
            raise HTTPException(404, str(err))


@router.post("/docs/{doc_id}/plot/styles")
def style_action(doc_id: str, body: StyleBody) -> dict:
    doc = _doc(doc_id)
    with doc.lock:
        runner = doc.get_runner()
        if body.action.casefold() in styleops.MUTATING and runner.run is not None:
            raise HTTPException(409, "A command is running; finish it first.")
        try:
            if body.action.casefold() in styleops.MUTATING:
                with doc.transaction("STYLESMANAGER"):
                    return styleops.apply(doc, body.action, body.args)
            return styleops.apply(doc, body.action, body.args)
        except (plotstyle.StyleError, L.LayoutError) as err:
            raise HTTPException(400, str(err))
        except OSError as err:
            raise HTTPException(400, "File error: %s" % err)
