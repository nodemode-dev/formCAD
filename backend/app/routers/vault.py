from typing import Any, Optional

from fastapi import APIRouter, HTTPException
from fastapi.responses import PlainTextResponse
from pydantic import BaseModel

from app.vault import commit, history, maint, mergeops, notes, pdm, refsops, registry, session, views
from app.vault.base import VaultError

router = APIRouter(tags=["vault"])


class CreateBody(BaseModel):
    name: str
    folder: Optional[str] = None
    attach: bool = False


class CheckinBody(BaseModel):
    path: Optional[str] = None
    doc_session: Optional[str] = None
    doc: Optional[str] = None
    name: Optional[str] = None
    branch: Optional[str] = None
    message: Optional[str] = None
    keep_lock: bool = False
    auto_merge: bool = True
    base: Optional[str] = None
    author: Optional[str] = None


class CheckoutBody(BaseModel):
    path: str
    branch: Optional[str] = None
    version: Optional[str] = None
    edit: bool = True
    lock: bool = True
    overwrite: bool = False
    open: bool = False
    author: Optional[str] = None


class UndoBody(BaseModel):
    path: str
    restore: bool = False


class BranchBody(BaseModel):
    name: str
    frm: Optional[str] = None
    author: Optional[str] = None


class RenameBody(BaseModel):
    to: str


class TagBody(BaseModel):
    name: str
    version: str


class MergeBody(BaseModel):
    source: str
    branch: Optional[str] = None
    author: Optional[str] = None


class ResolveBody(BaseModel):
    choices: dict[str, Any]


class CompleteBody(BaseModel):
    message: Optional[str] = None
    author: Optional[str] = None


class LockBody(BaseModel):
    note: Optional[str] = None
    force: bool = False
    author: Optional[str] = None


class StateBody(BaseModel):
    state: str
    revision: Optional[str] = None
    note: Optional[str] = None
    cascade: bool = False
    author: Optional[str] = None


class ReviseBody(BaseModel):
    branch: Optional[str] = None
    author: Optional[str] = None


class CommentBody(BaseModel):
    version: str
    entity: Optional[str] = None
    anchor: Optional[dict[str, Any]] = None
    body: str
    parent: Optional[int] = None
    markup_svg: Optional[str] = None
    camera: Optional[dict[str, Any]] = None
    author: Optional[str] = None


class CommentEdit(BaseModel):
    status: Optional[str] = None
    body: Optional[str] = None
    author: Optional[str] = None


class VerifyBody(BaseModel):
    doc: Optional[str] = None
    version: Optional[str] = None
    deep: bool = False


class GcBody(BaseModel):
    dry_run: bool = True
    grace_days: int = 30


def call(fn):
    try:
        return fn()
    except VaultError as err:
        raise HTTPException(err.status, err.message)


def vault(vid: str):
    return call(lambda: registry.get(vid))


@router.get("")
def vaults() -> dict:
    return call(lambda: {"vaults": registry.listing()})


@router.post("")
def create(body: CreateBody) -> dict:
    return call(lambda: registry.create(body.name, body.folder or "", body.attach))


@router.get("/{vid}")
def info(vid: str) -> dict:
    v = vault(vid)
    return call(lambda: registry.record_of(v))


@router.delete("/{vid}")
def forget(vid: str) -> dict:
    return call(lambda: registry.forget(vid))


@router.get("/{vid}/docs")
def docs(vid: str, q: str = "") -> dict:
    v = vault(vid)
    return call(lambda: {"docs": views.docs(v, q)})


@router.get("/{vid}/docs/{doc}")
def doc_info(vid: str, doc: str) -> dict:
    v = vault(vid)
    return call(lambda: views.doc(v, doc))


@router.post("/{vid}/checkin")
def checkin(vid: str, body: CheckinBody) -> dict:
    v = vault(vid)
    return call(lambda: session.checkin(v, body.doc_session or "", body.path or "", False, doc=body.doc or "", name=body.name or "", branch=body.branch or "", message=body.message or "", who=body.author or "", keep_lock=body.keep_lock, auto_merge=body.auto_merge, base=body.base or ""))


@router.post("/{vid}/docs/{doc}/checkout")
def checkout(vid: str, doc: str, body: CheckoutBody) -> dict:
    v = vault(vid)

    def run():
        res = commit.checkout(v, doc, body.path, body.version or body.branch or "", body.edit, body.lock, body.author or "", body.overwrite)
        return session.open_result(res) if body.open else res

    return call(run)


@router.post("/{vid}/undo-checkout")
def undo(vid: str, body: UndoBody) -> dict:
    v = vault(vid)
    return call(lambda: commit.undo_checkout(v, body.path, body.restore))


@router.get("/{vid}/binding")
def binding(vid: str, path: str) -> dict:
    v = vault(vid)
    return call(lambda: {"binding": commit.binding_of(v, path)})


@router.get("/{vid}/docs/{doc}/log")
def log(vid: str, doc: str, branch: str = "", limit: int = 200) -> dict:
    v = vault(vid)

    def run():
        with v.read() as c:
            history.doc_row(c, doc)
            start = history.resolve_ref(c, doc, branch) if branch else None
            return {"versions": history.log(c, doc, start, limit)}

    return call(run)


@router.get("/{vid}/docs/{doc}/graph")
def graph(vid: str, doc: str, limit: int = 300) -> dict:
    v = vault(vid)

    def run():
        with v.read() as c:
            history.doc_row(c, doc)
            return history.graph(c, doc, limit)

    return call(run)


@router.get("/{vid}/versions/{ver}")
def version(vid: str, ver: str) -> dict:
    v = vault(vid)
    return call(lambda: views.version(v, ver))


@router.get("/{vid}/versions/{ver}/entities")
def entities(vid: str, ver: str, kind: str = "", limit: int = 500) -> dict:
    v = vault(vid)
    return call(lambda: views.entity_list(v, ver, kind, limit))


@router.get("/{vid}/diff")
def diff(vid: str, a: str, b: str, limit: int = 500) -> dict:
    v = vault(vid)
    return call(lambda: views.diff(v, a, b, limit))


@router.get("/{vid}/docs/{doc}/branches")
def branches(vid: str, doc: str) -> dict:
    v = vault(vid)
    return call(lambda: refsops.listing(v, doc))


@router.post("/{vid}/docs/{doc}/branches")
def branch_create(vid: str, doc: str, body: BranchBody) -> dict:
    v = vault(vid)
    return call(lambda: refsops.create(v, doc, body.name, body.frm or "", body.author or ""))


@router.patch("/{vid}/docs/{doc}/branches/{name:path}")
def branch_rename(vid: str, doc: str, name: str, body: RenameBody) -> dict:
    v = vault(vid)
    return call(lambda: refsops.rename(v, doc, name, body.to))


@router.delete("/{vid}/docs/{doc}/branches/{name:path}")
def branch_delete(vid: str, doc: str, name: str, force: bool = False) -> dict:
    v = vault(vid)
    return call(lambda: refsops.delete(v, doc, name, force))


@router.post("/{vid}/docs/{doc}/tags")
def tag(vid: str, doc: str, body: TagBody) -> dict:
    v = vault(vid)
    return call(lambda: refsops.tag(v, doc, body.name, body.version))


@router.get("/{vid}/docs/{doc}/merge")
def merge_state(vid: str, doc: str) -> dict:
    v = vault(vid)
    return call(lambda: mergeops.state(v, doc))


@router.post("/{vid}/docs/{doc}/merge")
def merge_start(vid: str, doc: str, body: MergeBody) -> dict:
    v = vault(vid)
    return call(lambda: mergeops.start(v, doc, body.source, body.branch or "", body.author or ""))


@router.put("/{vid}/docs/{doc}/merge")
def merge_resolve(vid: str, doc: str, body: ResolveBody) -> dict:
    v = vault(vid)
    return call(lambda: mergeops.resolve(v, doc, body.choices))


@router.delete("/{vid}/docs/{doc}/merge")
def merge_abort(vid: str, doc: str) -> dict:
    v = vault(vid)
    return call(lambda: mergeops.abort(v, doc))


@router.post("/{vid}/docs/{doc}/merge/complete")
def merge_complete(vid: str, doc: str, body: CompleteBody) -> dict:
    v = vault(vid)
    return call(lambda: mergeops.complete(v, doc, body.message or "", body.author or ""))


@router.get("/{vid}/locks")
def locks(vid: str) -> dict:
    v = vault(vid)
    return call(lambda: {"locks": refsops.locks(v)})


@router.post("/{vid}/docs/{doc}/lock")
def lock(vid: str, doc: str, body: LockBody) -> dict:
    v = vault(vid)
    return call(lambda: refsops.lock(v, doc, body.author or "", body.note or ""))


@router.delete("/{vid}/docs/{doc}/lock")
def unlock(vid: str, doc: str, force: bool = False, note: str = "") -> dict:
    v = vault(vid)
    return call(lambda: refsops.break_lock(v, doc, "", note) if force else refsops.unlock(v, doc))


@router.post("/{vid}/versions/{ver}/state")
def state(vid: str, ver: str, body: StateBody) -> dict:
    v = vault(vid)
    return call(lambda: pdm.set_state(v, ver, body.state, body.revision or "", body.note or "", body.cascade, body.author or ""))


@router.post("/{vid}/docs/{doc}/revise")
def revise(vid: str, doc: str, body: ReviseBody) -> dict:
    v = vault(vid)
    return call(lambda: pdm.revise(v, doc, body.branch or "", body.author or ""))


@router.get("/{vid}/audit")
def audit(vid: str, doc: str = "", limit: int = 200) -> dict:
    v = vault(vid)
    return call(lambda: {"audit": pdm.audit(v, doc, limit)})


@router.get("/{vid}/docs/{doc}/whereused")
def whereused(vid: str, doc: str, version: str = "", scope: str = "heads") -> dict:
    v = vault(vid)
    return call(lambda: pdm.whereused(v, doc, version, scope))


@router.get("/{vid}/docs/{doc}/uses")
def uses(vid: str, doc: str, version: str = "") -> dict:
    v = vault(vid)
    return call(lambda: pdm.uses(v, doc, version))


@router.get("/{vid}/docs/{doc}/comments")
def comments(vid: str, doc: str, version: str = "", status: str = "") -> dict:
    v = vault(vid)
    return call(lambda: {"comments": notes.listing(v, doc, version, status)})


@router.post("/{vid}/docs/{doc}/comments")
def comment_add(vid: str, doc: str, body: CommentBody) -> dict:
    v = vault(vid)
    return call(lambda: notes.add(v, doc, body.version, body.entity or "", body.body, body.anchor, body.parent, body.markup_svg or "", body.camera, body.author or ""))


@router.patch("/{vid}/comments/{cid}")
def comment_edit(vid: str, cid: int, body: CommentEdit) -> dict:
    v = vault(vid)
    return call(lambda: notes.update(v, cid, body.status or "", body.body or "", body.author or ""))


@router.delete("/{vid}/comments/{cid}")
def comment_delete(vid: str, cid: int) -> dict:
    v = vault(vid)
    return call(lambda: notes.delete(v, cid))


@router.get("/{vid}/comments/{cid}/markup", response_class=PlainTextResponse)
def comment_markup(vid: str, cid: int) -> str:
    v = vault(vid)
    return call(lambda: notes.markup(v, cid))


@router.post("/{vid}/verify")
def verify(vid: str, body: VerifyBody) -> dict:
    v = vault(vid)
    return call(lambda: maint.verify(v, body.doc or "", body.version or "", body.deep))


@router.post("/{vid}/gc")
def gc(vid: str, body: GcBody) -> dict:
    v = vault(vid)
    return call(lambda: maint.gc(v, body.dry_run, body.grace_days))
