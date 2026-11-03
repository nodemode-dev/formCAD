from typing import Any, Optional

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel

from app.core import guard
from app.joints import contact, jobs, ops, study
from app.joints import store as J
from app.routers.mates import _doc, _edit, _read
from app.solid.work import SolidError

router = APIRouter(tags=["joints"])


class JointBody(BaseModel):
    type: str
    a: dict[str, Any]
    b: dict[str, Any]
    as_built: bool = False
    limits: Optional[dict[str, Any]] = None
    label: str = ""


class JointEdit(BaseModel):
    label: Optional[str] = None
    suppressed: Optional[bool] = None
    limits: Optional[dict[str, Any]] = None


class JointDrive(BaseModel):
    coord: str
    value: Optional[float] = None
    values: Optional[list[float]] = None
    start: Optional[float] = None
    end: Optional[float] = None
    count: Optional[int] = None
    max_step: Optional[float] = None
    commit: bool = True
    report: bool = False
    components: Optional[list[str]] = None


class LinkBody(BaseModel):
    first: dict[str, Any]
    second: dict[str, Any]
    ratio: float
    reverse: bool = False
    label: str = ""


class LinkEdit(BaseModel):
    ratio: Optional[float] = None
    reverse: Optional[bool] = None
    label: Optional[str] = None
    suppressed: Optional[bool] = None


def _key(v: str):
    return int(v) if str(v).isdigit() else v


@router.get("/{doc_id}/joints")
def list_joints(doc_id: str) -> dict:
    return _read(doc_id, ops.listing)


@router.post("/{doc_id}/joints")
def add_joint(doc_id: str, body: JointBody) -> dict:
    return _edit(doc_id, "JOINT", lambda doc: ops.add_joint(doc, body.type, body.a, body.b, body.as_built, body.limits, body.label))


@router.patch("/{doc_id}/joints/{jid}")
def edit_joint(doc_id: str, jid: str, body: JointEdit) -> dict:
    return _edit(doc_id, "JOINTEDIT", lambda doc: ops.set_joint(doc, _key(jid), body.label, body.suppressed, body.limits))


@router.delete("/{doc_id}/joints/{jid}")
def delete_joint(doc_id: str, jid: str) -> dict:
    return _edit(doc_id, "JOINTDELETE", lambda doc: ops.remove_joint(doc, _key(jid)))


@router.post("/{doc_id}/joints/{jid}/drive")
def drive_joint(doc_id: str, jid: str, body: JointDrive) -> dict:
    def run(doc):
        return ops.drive_joint(doc, _key(jid), body.coord, body.value, body.values, body.start, body.end, body.count, body.max_step, body.commit, body.report, body.components)

    return _edit(doc_id, "JOINTDRIVE", run) if body.commit else _read(doc_id, run)


@router.post("/{doc_id}/joints/{jid}/rest")
def rest_joint(doc_id: str, jid: str) -> dict:
    return _edit(doc_id, "JOINTDRIVE", lambda doc: ops.rest_joint(doc, _key(jid)))


@router.post("/{doc_id}/jointlinks")
def add_link(doc_id: str, body: LinkBody) -> dict:
    return _edit(doc_id, "JOINTLINK", lambda doc: ops.add_link(doc, body.first, body.second, body.ratio, body.reverse, body.label))


@router.patch("/{doc_id}/jointlinks/{lid}")
def edit_link(doc_id: str, lid: str, body: LinkEdit) -> dict:
    return _edit(doc_id, "JOINTLINK", lambda doc: ops.set_link(doc, _key(lid), body.ratio, body.reverse, body.label, body.suppressed))


@router.delete("/{doc_id}/jointlinks/{lid}")
def delete_link(doc_id: str, lid: str) -> dict:
    return _edit(doc_id, "JOINTLINK", lambda doc: ops.remove_link(doc, _key(lid)))


class StudyNew(BaseModel):
    name: Optional[str] = None
    duration: Optional[float] = None
    fps: Optional[int] = None


class StudyEdit(BaseModel):
    name: Optional[str] = None
    duration: Optional[float] = None
    fps: Optional[int] = None
    tracks: Optional[list[dict[str, Any]]] = None
    contact: Optional[dict[str, Any]] = None
    plots: Optional[list[dict[str, Any]]] = None


class ContactNew(BaseModel):
    name: Optional[str] = None
    all: bool = False
    pairs: Optional[list[list[str]]] = None
    touch: Optional[float] = None


class ContactEdit(BaseModel):
    name: Optional[str] = None
    all: Optional[bool] = None
    pairs: Optional[list[list[str]]] = None
    touch: Optional[float] = None


class SettingsBody(BaseModel):
    gravity: Optional[list[float]] = None
    density: Optional[float] = None
    servo_hz: Optional[float] = None
    damping_ratio: Optional[float] = None
    solref_loop: Optional[float] = None
    timestep: Optional[float] = None
    friction: Optional[float] = None
    contact_time: Optional[float] = None


class StudyRun(BaseModel):
    wait: bool = False
    frames: Optional[int] = None
    contact: Optional[str] = None


class ApplyBody(BaseModel):
    t: float


def restricted() -> bool:
    return bool(guard.CALLER.get())


def refuse(err):
    raise HTTPException(400, str(err))


@router.get("/{doc_id}/motion")
def motion_listing(doc_id: str) -> dict:
    out = _read(doc_id, lambda doc: study.listing(doc.drawing))
    out["limits"] = J.LIMITS
    return out


def motion_edit(doc_id: str, label: str, fn):
    try:
        return _edit(doc_id, label, fn)
    except (J.MotionError, jobs.JobError) as err:
        refuse(err)


def motion_read(doc_id: str, fn):
    try:
        return _read(doc_id, fn)
    except (J.MotionError, jobs.JobError) as err:
        refuse(err)


@router.post("/{doc_id}/motion/studies")
def study_new(doc_id: str, body: StudyNew) -> dict:
    caps = J.limits(restricted())
    return motion_edit(doc_id, "MOTIONSTUDY", lambda doc: {"study": study.new_study(doc.drawing, body.name, body.duration, body.fps, caps)})


@router.patch("/{doc_id}/motion/studies/{sid}")
def study_edit(doc_id: str, sid: str, body: StudyEdit) -> dict:
    caps = J.limits(restricted())
    fields = body.model_dump(exclude_unset=True)
    return motion_edit(doc_id, "MOTIONSTUDY", lambda doc: {"study": study.edit_study(doc.drawing, sid, fields, caps)})


@router.delete("/{doc_id}/motion/studies/{sid}")
def study_delete(doc_id: str, sid: str) -> dict:
    return motion_edit(doc_id, "MOTIONSTUDY", lambda doc: study.delete_study(doc.drawing, sid))


@router.post("/{doc_id}/motion/contacts")
def contact_new(doc_id: str, body: ContactNew) -> dict:
    caps = J.limits(restricted())
    return motion_edit(doc_id, "CONTACTSET", lambda doc: {"contact": contact.view(contact.new_set(doc.drawing, body.name, body.all, body.pairs, body.touch, caps))})


@router.patch("/{doc_id}/motion/contacts/{kid}")
def contact_edit(doc_id: str, kid: str, body: ContactEdit) -> dict:
    caps = J.limits(restricted())
    return motion_edit(doc_id, "CONTACTSET", lambda doc: {"contact": contact.view(contact.edit_set(doc.drawing, kid, body.name, body.all, body.pairs, body.touch, caps))})


@router.delete("/{doc_id}/motion/contacts/{kid}")
def contact_delete(doc_id: str, kid: str) -> dict:
    return motion_edit(doc_id, "CONTACTSET", lambda doc: contact.delete_set(doc.drawing, kid))


@router.put("/{doc_id}/motionsettings")
def motion_settings(doc_id: str, body: SettingsBody) -> dict:
    values = body.model_dump(exclude_none=True)
    return motion_edit(doc_id, "MOTIONSETTINGS", lambda doc: {"dynamics": J.apply_settings(doc.drawing, values)})


def job_view(job) -> dict:
    return job.view()


def start_job(doc_id: str, kind: str, label: str, prepare, wait: bool) -> dict:
    doc = _doc(doc_id)
    try:
        job = jobs.start(doc, kind, label, prepare, wait)
    except (J.MotionError, jobs.JobError) as err:
        refuse(err)
    except (ValueError, SolidError) as err:
        raise HTTPException(409, str(err))
    return job.view()


@router.post("/{doc_id}/motion/studies/{sid}/run")
def study_run(doc_id: str, sid: str, body: StudyRun) -> dict:
    flag = restricted()
    return start_job(doc_id, "study", sid, lambda doc: study.prepare(doc, sid, flag, body.contact, body.frames), body.wait)


class DynRun(BaseModel):
    study: Optional[str] = None
    duration: float
    timestep: Optional[float] = None
    record_fps: float = 60.0
    free: Optional[list[str]] = None
    contacts: Optional[list[str]] = None
    stop_on_contact: bool = False
    wait: bool = False


@router.post("/{doc_id}/motion/dynamics/run")
def dynamics_run(doc_id: str, body: DynRun) -> dict:
    from app.joints import dyn

    flag = restricted()
    spec = body.model_dump(exclude_none=True)
    wait = spec.pop("wait", False)
    return start_job(doc_id, "dynamics", str(spec.get("study") or ""), lambda doc: dyn.prepare(doc, spec, flag), wait)


def need_job(doc_id: str, jid: str):
    doc = _doc(doc_id)
    job = jobs.get(jid)
    if job is None or job.doc_id != doc.id:
        raise HTTPException(404, "No such motion run.")
    return doc, job


@router.get("/{doc_id}/motion/jobs")
def job_list(doc_id: str) -> dict:
    doc = _doc(doc_id)
    return {"jobs": jobs.listing(doc.id)}


@router.get("/{doc_id}/motion/jobs/{jid}")
def job_get(doc_id: str, jid: str) -> dict:
    return need_job(doc_id, jid)[1].view()


@router.get("/{doc_id}/motion/jobs/{jid}/frames")
def job_frames(doc_id: str, jid: str, start: int = Query(0, alias="from"), count: int = 200) -> dict:
    return study.frames_view(need_job(doc_id, jid)[1], start, count)


@router.post("/{doc_id}/motion/jobs/{jid}/cancel")
def job_cancel(doc_id: str, jid: str) -> dict:
    job = need_job(doc_id, jid)[1]
    jobs.cancel(jid)
    return job.view()


@router.post("/{doc_id}/motion/jobs/{jid}/apply")
def job_apply(doc_id: str, jid: str, body: ApplyBody) -> dict:
    job = need_job(doc_id, jid)[1]
    if job.state == "running":
        raise HTTPException(409, "The run is still going; wait for it or stop it first.")
    return motion_edit(doc_id, "MOTIONAPPLY", lambda doc: study.apply(doc, job, body.t))
