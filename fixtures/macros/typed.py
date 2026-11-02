import formcad

doc = formcad.active_document()

doc.send("CIRCLE")
doc.send("50,50")
doc.send("20")
doc.send("LINE 0,50 100,50 ")
doc.script("OFFSET\n5\n")
doc.command("polygon", sides=6, center=[50, 50], radius=30)

kinds = {}
for e in doc.entities():
    kinds[e["kind"]] = kinds.get(e["kind"], 0) + 1
assert kinds.get("circle") == 1 and kinds.get("line", 0) >= 1 and kinds.get("lwpolyline", 0) >= 1, kinds
before = doc.summary()["objects"]
doc.undo()
assert doc.summary()["objects"] == before - 1
doc.redo()
assert doc.summary()["objects"] == before
print("kinds", sorted(kinds.items()))
