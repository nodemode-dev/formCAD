---
name: assemblies-and-motion
description: Builds assemblies, mates, joints, motion studies and vault history in FormCAD. Use for inserting components, solving mates, interference, exploded views, BOM and kinematics.
---

# Assemblies and motion

Verified: `formcad_new_document` template `assembly`; `cmd_asminsert` with `path` (granted folder) and `position` [x,y,z] returns a component id (C1, C2); `cmd_matestatus` returns degrees of freedom per component; `cmd_interfere` returns interferences and clearances.

Mates: `cmd_mate` (`kind`, `first`, `second`, `value`; kinds include coincident, concentric, distance, angle, parallel, perpendicular, tangent, lock, gear, rackpinion, screw, limitdistance, limitangle), then `matesolve`, `matedrive`, `matedrag`, `explodeview`. BOM: `cmd_asmbom` with `action` show, export, renumber or assign. Components: `asmmove asmpattern asmconfig asmreplace asmreload asmflags`.

Joints and motion: `joint` (rigid, revolute, slider, cylindrical, pin-slot, planar, ball), `jointdrive`, `jointlink`, `contactset`, `motionstudy` (`action`), `dynamics`. Fixtures: `fixtures/mechanism.fcad`, `fixtures/linkage.fcad`.

Vault (read-only for agents): `vaultlog vaultdiff vaultwhereused vaultverify`; check-in, branch and merge exist as `vaultcheckin vaultbranch vaultmerge`; lifecycle commands are window only.
