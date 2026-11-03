# Assemblies, drawings and the vault

**Assemblies.** Components by safe file reference (`asminsert`), 13 mate kinds with degree-of-freedom counts (`mate`, `matestatus`), explode (`explodeview`), interference (`interfere`), bill of materials (`asmbom`). Contract: `docs/ASSEMBLY_SCHEMA.md`.

**Joints and motion.** `joint`, `motionstudy`, `contactset`, `dynamics`. Dynamics is unavailable on Intel Macs.

**Drawings.** Views from 3D (`viewbase`, `viewprojected`, `viewsection`, `viewdetail`), model dimensions (`viewdim`), tolerance frames (`gdtframe`), balloons (`balloon`), tables (`bomtable`), title blocks (`titleblock`).

**Inspection.** `inspection`, `inspectionexport`, `mbdview` for numbered characteristics and model-based views.

**The vault.** A local content-addressed store: `vaultcheckin`, `vaultbranch`, `vaultmerge`, `vaultlock`, `vaultrevise`, `vaultwhereused`. Local only, no server. Macros and agents cannot create or administer a vault.

See manual chapters 10 to 12, 14 and 23.
