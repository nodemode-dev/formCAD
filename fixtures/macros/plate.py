import math

import formcad

doc = formcad.active_document()

plate = doc.rectangle([0, 0], [120, 80])
holes = [doc.circle(c, 6) for c in ([15, 15], [105, 15], [105, 65], [15, 65])]
doc.line([60, -10], [60, 90])
doc.send("TEXT")
doc.send("10,-20")
doc.send("5")
doc.send("0")
doc.send("PLATE 120 x 80")

circles = doc.entities(kind="circle")
assert len(circles) == 4, circles
assert all(abs(c["radius"] - 6) < 1e-9 for c in circles)

doc.move(holes[:2], [0, 10])
doc.scale(holes[2:], [105, 65], 1.5)
copies = doc.command("copy", handles=[plate], delta=[0, 120])
assert copies, copies

by_handle = {c["handle"]: c for c in doc.entities(kind="circle")}
assert abs(by_handle[holes[0]]["center"][1] - 25) < 1e-9
assert abs(by_handle[holes[2]]["radius"] - 9) < 1e-9

doc.select(holes[:1])
assert doc.selection() == holes[:1]
doc.erase(holes[:1])
assert len(doc.entities(kind="circle")) == 3
doc.undo()
assert len(doc.entities(kind="circle")) == 4
doc.redo()
assert len(doc.entities(kind="circle")) == 3
doc.undo()

lengths = []
for e in doc.entities(kind="line"):
    lengths.append(math.dist(e["start"][:2], e["end"][:2]))
assert abs(max(lengths) - 100) < 1e-9, lengths

summary = doc.summary()
print("objects", summary["objects"], "extents", summary["extents"])
