# FormCAD wiki

FormCAD is an Apache-2.0 desktop CAD app for macOS, Linux and Windows: 2D drafting, parametric parts, surfaces, assemblies, drawings, manufacture, simulation, electronics and automation, driven by one engine that you can also run headless or hand to an agent.

Version: v0.20.1.

## Start here

- [[Getting-Started]] · install, boot, first drawing
- [[Architecture]] · the interface, the engine, the kernel worker, the mesher
- [[Workspaces]] · what each workspace does, by group
- [[Automation-and-Agents]] · LISP, macros, plugins, the CLI, MCP and the trust model
- [[Building-and-Releasing]] · the dispatcher, the freezes, the release folder
- [[Licensing-and-Data-Provenance]] · what runs where under which licence, and why no standard tables ship
- [[Contributing]] · the laws

The full user manual is `docs/MANUAL.md` in the repository.

## Three facts worth knowing early

1. 3D work runs in a separate program, the kernel worker. Without it you still have 2D, meshes and the graph's non-solid nodes.
2. Macros and agents are trusted less than the window, by design.
3. FormCAD ships formulas and empty tables, not copies of standards. Your data is yours.
