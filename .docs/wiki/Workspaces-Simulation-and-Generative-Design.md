# Simulation and generative design

**Simulation.** Materials with sources, loads, fixtures, contacts and mesh controls (`simmaterial`, `simload`, `simfixture`, `simcontact`, `simcontrol`), then `simstudy` and `simrun`, results with `simprobe` and `simreport`. Linear static, modal, thermal, thermal stress and buckling are the solid base; nonlinear, contact, events, fatigue and laminates are first versions. A separate mesher program is needed.

**Flow.** Laminar duct flow, cooling and injection fill estimates on FormCAD's own code; an optional link to a flow solver you install yourself.

**Topology and shape.** `toporun`, `topoapply`, `toposhape`: optimization with a stress check, turned into a mesh body.

**Generative design.** `genrun`, `genapply`: several outcomes under preserved and obstacle regions, loads, a safety factor and manufacturing methods.

**Limits.** Memory is checked before every solve; results on a voxel grid are smoothed and are guidance, not certification. See manual chapters 17 and 18.
