from app.doc.service import DocumentFault, service
from app.vault import commit, history, refsops, registry, views
from app.vault.base import VaultError


def open_doc(session_id: str):
    try:
        return service.get(session_id)
    except DocumentFault as err:
        raise VaultError(err.message, err.status)


def save_doc(doc) -> str:
    if not doc.path:
        raise VaultError("The document has no file yet; save it before checking it in.")
    try:
        service.save(doc)
    except DocumentFault as err:
        raise VaultError(err.message, err.status)
    return doc.path


def save_for_checkin(session_id: str) -> str:
    doc = open_doc(session_id)
    with doc.lock:
        if doc.get_runner().run is not None:
            raise VaultError("A command is running; finish it first.", 409)
    return save_doc(doc)


def checkin(v, session_id: str = "", path: str = "", agent: bool = False, **kw) -> dict:
    if session_id:
        path = save_for_checkin(session_id)
    return commit.checkin(v, path=path, agent=agent, **kw)


def open_result(result: dict) -> dict:
    try:
        doc = service.open(result["path"])
    except DocumentFault as err:
        raise VaultError(err.message, err.status)
    result["session"] = doc.id
    return result


def status_of(session_id: str) -> dict:
    doc = open_doc(session_id)
    out = {"bound": False, "vault": "", "path": doc.path or "", "binding": None, "doc": None, "lock": None}
    if not doc.path:
        return out
    for item in registry.listing():
        if not item.get("available"):
            continue
        v = registry.get(item["id"])
        b = commit.binding_of(v, doc.path)
        if b:
            out.update({"bound": True, "vault": item["id"], "binding": b, "lock": b.get("lock")})
            with v.read() as c:
                out["doc"] = views.doc_record(c, history.doc_row(c, b["doc"]))
            return out
    return out


def lock_for(v, doc: str):
    return refsops.doc_lock(v, doc)
