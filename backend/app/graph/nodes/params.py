from app.graph.nodes.common import P, add

FAMILY = (
    ("number", "Number", "Num", "number", "81a2def7-03fa-4119-8ce4-3f42d9c5166c", "Holds real numbers."),
    ("integer", "Integer", "Int", "integer", "a5f189fc-6317-4ede-a338-ea375f9dfc99", "Holds whole numbers; fractions are rounded."),
    ("boolean", "Boolean", "Bool", "boolean", "e08585a3-23f6-49ee-90c2-913cc0a59f0d", "Holds true or false values."),
    ("text", "Text", "Txt", "text", "efe335ee-f18d-4db9-a431-1497b267940e", "Holds text strings."),
    ("point", "Point", "Pt", "point", "adb45f49-1513-4227-b5ab-f5ab00a7dd16", "Holds points in space."),
    ("vector", "Vector", "Vec", "vector", "7f052703-73a5-4df9-99f6-364802cbdc48", "Holds direction vectors."),
    ("plane", "Plane", "Pln", "plane", "def450f4-1180-4290-9b24-ab1fd9f03b60", "Holds planes (an origin and an orthonormal frame)."),
    ("domain", "Domain", "Dom", "domain", "b2786066-487b-4820-84de-f45acf594341", "Holds numeric intervals; a number n becomes the domain 0 to n."),
    ("colour", "Colour", "Col", "colour", "ae79385b-1e49-4484-a7e9-0e0c4044d992", "Holds colours."),
    ("any", "Data", "Any", "any", "be946931-a549-42d8-b7c5-3d30f54eb5aa", "Holds data of any type and keeps its tree structure."),
)


def make(kind_id, name, nick, kind, guid, text):
    def run(ctx, trees):
        return {"value": trees["value"]}

    add(
        "param." + kind_id, guid, name, nick, "Params", "Primitive",
        [P("value", kind, "tree", None, "V", "The stored or incoming data, passed on with its paths unchanged.")],
        [P("value", kind, "tree", None, "V", "The data after type conversion.")],
        run=run, description=text,
    )


for row in FAMILY:
    make(*row)
