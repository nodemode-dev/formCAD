from app.assembly import parts
from app.doc.document import Document
from app.doc.model import Drawing
from app.doc.service import service


class VariantError(Exception):
    pass


def variant(lp, name: str):
    if name in lp.variants:
        return lp.variants[name]
    if name not in lp.configs:
        raise VariantError("The part has no configuration called %s." % name)
    from app.bodies import configs as C

    d2 = Drawing.from_dict(lp.drawing.to_dict())
    d2.blobs.update(lp.drawing.blobs)
    doc = Document(d2, "variant", "", "part", d2.metric)
    service.docs[doc.id] = doc
    try:
        with doc.lock:
            doc.begin("VARIANT")
            try:
                C.activate(d2, name)
            except BaseException:
                doc.rollback()
                raise
            doc.commit(False)
    except Exception as err:
        raise VariantError(str(getattr(err, "message", err)))
    finally:
        service.docs.pop(doc.id, None)
    var = parts.LoadedPart(lp.path, lp.sig, d2, "part")
    var.active_config = name
    var.variants = {}
    lp.variants[name] = var
    return var
