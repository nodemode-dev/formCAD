# Kernel worker notices

The `formcad-kernel` worker is a separate program shipped only from the `formCAD-binaries` releases, never inside the FormCAD app or its installers. Licences below were read from the owners' repositories (R15), because several PyPI pages leave the licence field blank. The release archive must carry the full licence texts listed here.

| Work | Version | Licence | Read from |
| --- | --- | --- | --- |
| OpenCascade Technology (inside the cadquery-ocp-novtk wheel, as replaceable shared libraries) | 8.0.1 | LGPL-2.1 with the Open CASCADE exception 1.0 | github.com/Open-Cascade-SAS/OCCT, `LICENSE_LGPL_21.txt` and `OCCT_LGPL_EXCEPTION.txt` |
| cadquery-ocp-novtk (OCP bindings) | 8.0.1.1.0 | Apache-2.0 | pypi.org/project/cadquery-ocp-novtk and github.com/CadQuery/OCP |
| build123d | 0.13.0 | Apache-2.0 | pypi.org/project/build123d and github.com/gumyr/build123d |
| ocpsvg | 0.7.x | Apache-2.0 (PyPI metadata is blank; the repository LICENSE file is the Apache-2.0 text) | github.com/snoyer/ocpsvg, `LICENSE` |
| bd_materials | 0.2.x | Apache-2.0 (PyPI metadata is blank; the repository LICENSE file is the Apache-2.0 text) | github.com/bernhard-42/bd_materials, `LICENSE` |
| anytree | 2.13.0 | Apache-2.0 (PyPI metadata is blank; the repository shows Apache-2.0) | github.com/c0fec0de/anytree |
| threejs-materials | 1.2.x | Apache-2.0 for the package; FLAG: the texture sets it downloads come from ambientCG, GPUOpen MaterialX Library, PolyHaven and PhysicallyBased, and the package page states no licence for them | pypi.org/project/threejs-materials |
| ocp_gordon, svgpathtools, trianglesolver, ezdxf, lib3mf, numpy, scipy, sympy, ipython, webcolors, fonttools | as pinned by build123d | Apache-2.0, MIT, MIT, MIT, BSD, BSD-3-Clause and others, BSD, BSD, BSD-3-Clause, BSD-3-Clause, MIT | the PyPI pages in R15 section 1 |

Open items before the first kernel release:

- Texture assets: the worker never calls threejs-materials and downloads no texture. Do not ship or fetch any texture until each source's licence is reviewed.
- Not checked in R15: requests, typing_extensions, svgelements and the transitive dependencies of ipython. Check them when the release archive is assembled.
- The release archive carries a prominent notice that it uses OpenCascade Technology, as the Open CASCADE exception requires.
