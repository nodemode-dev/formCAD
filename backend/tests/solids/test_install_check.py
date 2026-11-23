import hashlib
import io
import shutil
import tarfile

import pytest

RELEASE = "9.9.9"
FILES = {
    "README.md": b"formCAD kernel test release\n",
    "LGPL-2.1.txt": b"licence text stand-in\n",
    "lib/libshapes.so": bytes(range(256)) * 8,
}


@pytest.fixture()
def release(tmp_path, monkeypatch):
    from app.services import kernel as service

    target = service.triple()
    root = tmp_path / "installed"
    monkeypatch.setattr(service, "kernel_root", lambda: root)
    monkeypatch.setitem(service._install, "message", "")
    monkeypatch.setitem(service._install, "progress", 0.0)
    monkeypatch.setitem(service._install, "installing", False)

    def make(files=FILES, record_files=FILES, extra_members=()):
        archive = tmp_path / "release.tar.gz"
        folder = "occt-lgpl-%s-%s" % (RELEASE, target)
        with tarfile.open(archive, "w:gz") as bundle:
            for rel, data in list(files.items()) + list(extra_members):
                info = tarfile.TarInfo(rel if rel.startswith("..") else "%s/%s" % (folder, rel))
                info.size = len(data)
                bundle.addfile(info, io.BytesIO(data))
        monkeypatch.setattr(service, "download", lambda url, dest: shutil.copyfile(archive, dest))
        rec = {
            "release": RELEASE,
            "url": "https://example.invalid/{release}/{triple}.tar.gz",
            "folder": "occt-lgpl-{release}-{triple}",
            "files": [{"triple": target, "path": rel, "sha256": hashlib.sha256(data).hexdigest()} for rel, data in record_files.items()],
        }
        service.run_install(rec, RELEASE, target)
        return root / RELEASE, service.status()["message"]

    return make


@pytest.mark.kernel
def test_a_release_whose_every_file_matches_the_record_is_installed(release):
    folder, message = release()
    assert message == "Kernel installed."
    assert {p.relative_to(folder).as_posix(): p.read_bytes() for p in folder.rglob("*") if p.is_file()} == FILES


@pytest.mark.parametrize("case, named", [
    ("changed", "lib/libshapes.so does not match the recorded SHA-256"),
    ("missing", "LGPL-2.1.txt is missing"),
    ("unrecorded", "notes.txt is not in the shipped record"),
])
def test_a_release_with_a_changed_missing_or_unrecorded_file_is_refused_and_nothing_is_installed(release, case, named):
    files = dict(FILES)
    if case == "changed":
        files["lib/libshapes.so"] = FILES["lib/libshapes.so"][:-1] + b"\x00"
    elif case == "missing":
        del files["LGPL-2.1.txt"]
    else:
        files["notes.txt"] = b"not shipped\n"
    folder, message = release(files=files)
    assert named in message and message.endswith("Nothing was installed.")
    assert not folder.exists()


def test_a_refused_release_leaves_the_kernel_already_installed_untouched(release):
    from app.services import kernel as service

    earlier = service.kernel_root() / RELEASE
    earlier.mkdir(parents=True)
    (earlier / "README.md").write_bytes(b"the earlier good install\n")
    files = dict(FILES)
    files["README.md"] = b"tampered\n"
    folder, message = release(files=files)
    assert "README.md does not match" in message
    assert sorted(p.name for p in folder.iterdir()) == ["README.md"]
    assert (folder / "README.md").read_bytes() == b"the earlier good install\n"


def test_a_release_with_a_member_that_escapes_the_folder_is_refused(release, tmp_path):
    folder, message = release(extra_members=[("../../escaped.txt", b"outside\n")])
    assert "Nothing was installed." in message
    assert not folder.exists()
    assert not list(tmp_path.parent.rglob("escaped.txt"))
