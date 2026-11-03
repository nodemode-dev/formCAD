import io
import zipfile

from app.sim.fem import SimError

MAX_MEMBER = 300 * 1048576
MAX_TOTAL = 400 * 1048576


def checked(source):
    if isinstance(source, (bytes, bytearray)):
        source = io.BytesIO(source)
    try:
        with zipfile.ZipFile(source) as z:
            sizes = [i.file_size for i in z.infolist()]
    except (zipfile.BadZipFile, OSError):
        raise SimError("A stored array file is damaged.")
    if sizes and (max(sizes) > MAX_MEMBER or sum(sizes) > MAX_TOTAL):
        raise SimError("A stored array file expands to %d MB, over the limit of %d MB. The file was not read." % (sum(sizes) // 1048576, MAX_TOTAL // 1048576))
    if hasattr(source, "seek"):
        source.seek(0)
    return source
