# Licensing and data provenance

## The app

FormCAD is Apache-2.0. Copyright 2026 NodeAgentc, Inc. See `LICENSE` and `NOTICE.md`.

## Three tiers

1. **Permissive, in process.** Apache, MIT, BSD and similar libraries may run inside the engine or the interface. Heavy numerical work that is permissive (numpy, scipy, a finite element library under a BSD licence) runs in the engine inside a cancellable job.
2. **LGPL, in a separate program.** The OpenCascade kernel and the Netgen mesher are LGPL. They run as their own programs (`kernel/`, `mesher/`), speak to the engine over a pipe, are never linked into the engine and are downloaded as separately replaceable, unpatched binaries with their notices and a source offer.
3. **GPL tools, optional and user-installed.** Programs under the GPL (a flow solver, a finite element solver, an electronics suite, a simulator) are never bundled and never required. They are off by default, found at a path the user sets, and spoken to only over a process boundary with an argument list, a timeout and bounded output. The converter for DWG files follows the same pattern.

GPL and AGPL code never enters a distributed build. Code from the sibling GPL projects is never copied; FormCAD meets their data contracts only.

## Clean room

FormCAD is written from functional specifications. Nobody opens, fetches, quotes or copies another CAD product's code, and no commercial product is named in code, identifiers, comments or the interface, except file-format names.

## Why no standard tables ship

Standards tables (fastener sizes, structural profiles, bend tables, tube data, cost rates, emission factors) are copyrighted compilations or carry terms that do not allow redistribution. FormCAD therefore:

- ships a **formula** where one exists (a bend deduction from K-factor, a land pattern from a rule),
- ships an **empty, user-editable table** where the data is a table, or
- ships a value only with a **cited source for each value** whose terms allow it (the simulation materials name their handbook and page; plastic rules name theirs).

The toolbox generates hardware from sizes you enter. The weldment profiles come from dimensions you enter. The cost profile starts empty. Rule values carry a source and a flag when only one source supports them. If a value has no source, it is blank, and the interface says so.

## Notices

Every dependency, binary, font and asset gets a `NOTICE.md` row before it lands, with its licence and where it lives. The numpy and scipy wheels carry some LGPL and runtime-exception libraries as separate, unmodified shared files; the notice rows say which.
