# Mesher worker notices

The `formcad-mesher` worker is a separate program shipped only from the `formCAD-binaries` releases, never inside the FormCAD app or its installers, and never in the same process as the kernel worker (its OpenCascade 7.8.1 build is not the 8.0.1 build of the kernel). Everything below was read from the installed wheels of the release pins (`mesher/requirements_mesher.txt`) on Linux x86_64, CPython 3.13. The release archive must carry the full licence texts named here.

| Work | Version | Licence | Read from |
| --- | --- | --- | --- |
| netgen-mesher (Netgen and NGSolve core libraries `libngcore`, `libnglib`, `libngpy` and the Python modules `netgen`, `pyngcore`) | 6.2.2608 | LGPL-2.1-only (wheel `License-Expression`; `licenses/LICENSE` is the GNU LGPL 2.1 text; `licenses/AUTHORS` names Joachim Schoeberl) | `netgen_mesher-6.2.2608.dist-info/METADATA` and `licenses/` |
| netgen-occt (OpenCascade 7.8.1 shared libraries, 28 of its libTK libraries load when a STEP or BRep shape is meshed, placed by the wheel in `<prefix>/lib`) | 7.8.1 | LGPL-2.1 (classifier LGPLv2+; wheel ships `licenses/LICENSE_LGPL_21.txt`); the OpenCascade exception text is not shipped in the wheel, check before release | `netgen_occt-7.8.1.dist-info/METADATA` and `licenses/` |
| numpy | 2.5.4 | BSD-3-Clause; its Linux wheel carries OpenBLAS (BSD-3-Clause), libgfortran (GPL-3.0 with the GCC Runtime Library Exception) and libquadmath (LGPL-2.1) as separate libraries in `numpy.libs`, which also load in this program | the engine's NOTICE row |
| libGLU 1.3.1, libXmu 6.2.0, libXt 6.0.0 (in `netgen_mesher.libs`, for the Netgen GUI), `libnggui`, `libtogl.a`, `ng_mpich.so`, `ng_openmpi.so` | as bundled | NOT VERIFIED: the wheel's SBOM (`sboms/auditwheel.cdx.json`) names libXmu 1.1.3, libXt 1.1.5 and mesa-libGLU 9.0.0 (AlmaLinux 8 packages) and states no licences; they are normally X11 or SGI-style permissive licences. None of them loads when the program meshes a shape (checked in `/proc/self/maps`), and the freeze script excludes the GUI modules | the SBOM, and a run of `netgen.occ` and `netgen.meshing` |

Open items before the first mesher release:

- Confirm the licences of libGLU, libXmu and libXt from their package sources, or drop them from the archive (the freeze excludes the GUI modules; `libnggui` and the MPI wrappers are not loaded).
- Netgen on Linux ARM and Windows ARM has no wheel; the mesher is unavailable there (R25 section 1).
- The release archive carries a notice that it uses OpenCascade Technology and the Netgen source offer (LGPL-2.1: the unmodified libraries stay replaceable shared libraries in the onedir folder).
