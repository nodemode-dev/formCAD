from dataclasses import dataclass, field
from typing import Any

from app.doc.tables import DIM_DEFAULTS, LINEWEIGHTS


@dataclass
class VarDef:
    name: str
    type: str
    default: Any
    scope: str
    rule: tuple = ("any",)
    desc: str = ""
    profile: bool = False
    hidden: bool = False
    angle: bool = False
    dim: bool = False
    flags: dict = field(default_factory=dict)

    @property
    def readonly(self) -> bool:
        return self.scope == "readonly"

    def default_for(self, metric: bool):
        d = self.default
        if isinstance(d, tuple) and len(d) == 3 and d[0] == "pair":
            return d[2] if metric else d[1]
        return d


def _pair(imperial, metric):
    return ("pair", imperial, metric)


TOGGLE = ("set", (0, 1))

VARS: list = []


def _add(name, type_, default, scope, rule, desc, **kw):
    VARS.append(VarDef(name, type_, default, scope, rule, desc, **kw))


def S(name, default, rule, desc, type_="int", **kw):
    _add(name, type_, default, "session", rule, desc, **kw)


def P(name, default, rule, desc, type_="int", **kw):
    _add(name, type_, default, "session", rule, desc, profile=True, **kw)


def D(name, default, rule, desc, type_="int", **kw):
    _add(name, type_, default, "drawing", rule, desc, **kw)


def R(name, type_, default, desc, **kw):
    _add(name, type_, default, "readonly", ("any",), desc, **kw)


S("OSMODE", 4133, ("range", 0, 32767), "Running object snap modes (bit sum)")
S("OSNAPHATCH", 0, TOGGLE, "Object snaps find hatch objects")
S("ORTHOMODE", 0, TOGGLE, "Ortho on")
S("POLARMODE", 0, ("range", 0, 15), "Polar tracking option bits")
S("POLARANG", 90.0, ("gt", 0), "Polar angle increment in degrees", "real")
S("POLARADDANG", "", ("list",), "Additional polar angles separated by semicolons", "string")
S("POLARDIST", 0.0, ("range", 0, 1e12 - 1), "PolarSnap step (0 uses snap X spacing)", "real")
S("SNAPTYPE", 0, TOGGLE, "0 grid snap, 1 PolarSnap")
S("AUTOSNAP", 61, ("range", 0, 63), "Marker, tooltip and tracking bits")
S("GRIDMODE", 1, TOGGLE, "Grid displayed")
S("SNAPMODE", 0, TOGGLE, "Snap on")
S("SNAPSTYL", 0, TOGGLE, "0 standard, 1 isometric")
S("SNAPISOPAIR", 0, ("range", 0, 2), "Current isometric plane (0 left, 1 top, 2 right)")
D("SNAPUNIT", [0.5, 0.5], ("point", "pos"), "Snap spacing X,Y", "point")
D("GRIDUNIT", [0.5, 0.5], ("point", "nonneg"), "Grid spacing X,Y (zero follows SNAPUNIT)", "point")
S("GRIDMAJOR", 5, ("range", 1, 100), "Major grid line every N lines")
D("SNAPBASE", [0.0, 0.0], ("point", "any"), "Snap grid origin", "point")
D("SNAPANG", 0.0, ("any",), "Snap grid rotation in degrees", "real", angle=True)
S("DYNMODE", 1, TOGGLE, "Dynamic input on")
S("DYNPROMPT", 1, TOGGLE, "Dynamic input prompt beside cursor")
S("DYNPIFORMAT", 0, TOGGLE, "Second points shown Cartesian (1) or polar (0)")
S("DYNPICOORDS", 0, TOGGLE, "Second points absolute (1) or relative (0)")
S("DYNDIGRIP", 31, ("range", 0, 31), "Grip dimensions shown (bits)")
S("DYNDIVIS", 1, ("range", 0, 2), "How many grip dimensions show")
D("ANGBASE", 0.0, ("any",), "Direction of angle zero in degrees", "real", angle=True)
D("ANGDIR", 0, TOGGLE, "Positive angle direction (0 counter-clockwise, 1 clockwise)")
R("LASTPOINT", "point", [0.0, 0.0, 0.0], "Last point entered")

S("PICKBOX", 3, ("range", 0, 50), "Pick box half size in pixels")
S("APERTURE", 10, ("range", 1, 50), "Object snap aperture in pixels")
S("PICKFIRST", 1, TOGGLE, "Noun-verb selection")
S("PICKADD", 1, TOGGLE, "Picks add to the selection")
S("PICKDRAG", 2, ("set", (0, 2)), "0 two-click windows, 2 click or drag")
S("PICKSTYLE", 1, ("range", 0, 3), "Bit 1 group selection, bit 2 associative hatch")
S("SELECTIONCYCLING", -2, ("range", -2, 2), "Cycling display level; negative is off")
S("SELECTSIMILARMODE", 130, ("range", 0, 255), "Properties SELECTSIMILAR matches (bits)")
S("OBJECTISOLATIONMODE", 0, ("set", (0,)), "Isolation mode (0 temporary)")
S("HIGHLIGHT", 1, TOGGLE, "Highlight selected objects")
S("SELECTIONEFFECT", 1, TOGGLE, "0 dashed, 1 redrawn in selection colour")
S("SELECTIONPREVIEW", 3, ("range", 0, 3), "Hover highlight bits")
S("PREVIEWEFFECT", 2, ("range", 0, 2), "0 dashed, 1 thicker, 2 both")
S("PREVIEWFILTER", 3, ("range", 0, 63), "Never-highlighted bits")
S("GRIPS", 1, ("range", 0, 2), "Grips shown")
S("GRIPOBJLIMIT", 100, ("range", 0, 32767), "No grips above this selection size (0 no limit)")
S("GRIPSIZE", 5, ("range", 1, 255), "Grip size in pixels")
S("SELECTIONAREA", 1, TOGGLE, "Fill window and crossing areas")
S("WINDOWAREACOLOR", 150, ("range", 1, 255), "Window area colour (ACI)")
S("CROSSINGAREACOLOR", 100, ("range", 1, 255), "Crossing area colour (ACI)")
S("SELECTIONAREAOPACITY", 25, ("range", 0, 100), "Fill opacity percent")
S("CURSORSIZE", 5, ("range", 1, 100), "Crosshair size percent")
S("QPMODE", 0, ("any",), "Quick properties palette on selection")

S("ZOOMFACTOR", 60, ("range", 3, 100), "Mouse wheel zoom strength")
D("LWDISPLAY", 0, TOGGLE, "Show lineweights on screen")
S("TRANSPARENCYDISPLAY", 1, TOGGLE, "Show transparency on screen")
S("PLOTTRANSPARENCYOVERRIDE", 1, ("range", 0, 2), "0 never plot transparency, 1 follow page setup, 2 always")
R("VIEWCTR", "point", [0.0, 0.0, 0.0], "Centre of the current view")
R("VIEWSIZE", "real", 0.0, "Height of the current view")
R("EXTMIN", "point", [0.0, 0.0, 0.0], "Lower corner of the current space extents")
R("EXTMAX", "point", [0.0, 0.0, 0.0], "Upper corner of the current space extents")
D("LIMMIN", [0.0, 0.0], ("point", "any"), "Lower drawing limit", "point")
D("LIMMAX", _pair([12.0, 9.0], [420.0, 297.0]), ("point", "any"), "Upper drawing limit", "point")
R("TILEMODE", "int", 1, "1 in the Model tab, 0 in a layout")
R("CTAB", "string", "Model", "Name of the current tab")

S("CMDECHO", 1, TOGGLE, "Command echo for routines")
S("FILEDIA", 1, TOGGLE, "File dialogs for routines")
S("ACADLSPASDOC", 0, TOGGLE, "Startup routine file loads into every drawing")
S("MAXARRAY", 100000, ("range", 100, 10000000), "Most objects one array command creates")
S("MEASUREINIT", 0, TOGGLE, "Units of a new drawing without a template")
P("QNEWTEMPLATE", "", ("text",), "Template file NEW starts from", "string")
S("AUDITCTL", 0, TOGGLE, "AUDIT also writes a report file")
S("ATTREQ", 1, TOGGLE, "INSERT asks for attribute values")
P("SAVETIME", 10, ("range", 0, 600), "Autosave interval in minutes (0 off)")
P("SAVEFILEPATH", "", ("text",), "Autosave folder", "string")
P("ISAVEBAK", 1, TOGGLE, "Keep a backup copy when saving over a file")
P("FONTALT", "", ("text",), "Font used when a text font is missing", "string")
P("FONTFALLBACK", "", ("text",), "Ordered fallback fonts list", "string")
R("CMDNAMES", "string", "", "Name of the running command")
R("CMDACTIVE", "int", 0, "1 while a command runs")
R("DWGNAME", "string", "", "Drawing title")
R("DWGPREFIX", "string", "", "Folder of the drawing file")
R("DWGTITLED", "int", 0, "1 once the drawing has a file")
R("DBMOD", "int", 0, "1 when there are unsaved changes")
R("PLATFORM", "string", "", "Operating system name")
R("BLOCKEDITOR", "int", 0, "1 while the block editor is open")
R("UNDOCTL", "int", 53, "Undo state bits")
R("UNDOMARKS", "int", 0, "Reachable undo marks")

D("LUNITS", 2, ("range", 1, 5), "Linear units: 1 scientific, 2 decimal, 3 engineering, 4 architectural, 5 fractional")
D("LUPREC", 4, ("range", 0, 8), "Linear precision")
D("AUNITS", 0, ("range", 0, 4), "Angular units: 0 degrees, 1 DMS, 2 grads, 3 radians, 4 surveyor")
D("AUPREC", 0, ("range", 0, 8), "Angular precision")
D("INSUNITS", _pair(1, 4), ("range", 0, 24), "Insertion units")
D("MEASUREMENT", _pair(0, 1), TOGGLE, "0 imperial, 1 metric")
D("CLAYER", "0", ("name", "layers"), "Current layer", "string")
D("CECOLOR", 256, ("color",), "Current colour", "color")
D("CELTYPE", "ByLayer", ("name", "linetypes"), "Current linetype", "string")
D("CELWEIGHT", -1, ("lw", True), "Current lineweight (-1 ByLayer)")
D("CELTSCALE", 1.0, ("gt", 0), "Current object linetype scale", "real")
D("LTSCALE", 1.0, ("gt", 0), "Global linetype scale", "real")
D("PSLTSCALE", 1, TOGGLE, "Paper space linetype scaling")
D("TEXTSTYLE", "Standard", ("name", "textstyles"), "Current text style", "string")
D("TEXTSIZE", _pair(0.2, 2.5), ("gt", 0), "Default text height", "real")
D("DIMSTYLE", "Standard", ("name", "dimstyles"), "Current dimension style", "string")
D("CMLEADERSTYLE", "Standard", ("name", "mleaderstyles"), "Current multileader style", "string")
D("CTABLESTYLE", "Standard", ("name", "tablestyles"), "Current table style", "string")
R("CPLOTSTYLE", "string", "ByLayer", "Current plot style")
D("CANNOSCALE", "1:1", ("name", "scales"), "Current annotation scale", "string")
R("CANNOSCALEVALUE", "real", 1.0, "Paper units per drawing unit of the current annotation scale")
D("ANNOALLVISIBLE", 1, TOGGLE, "Show annotative objects at all scales")
D("ANNOAUTOSCALE", -4, ("range", -4, 4), "Add the current scale to annotative objects when it changes")
D("PDMODE", 0, ("any",), "Point display mode")
D("PDSIZE", 0.0, ("any",), "Point display size", "real")
D("FILLMODE", 1, TOGGLE, "Fill solids and hatches")
D("MIRRTEXT", 0, TOGGLE, "Mirror text with MIRROR")
D("ATTMODE", 1, ("range", 0, 2), "Attribute display (0 off, 1 normal, 2 all)")
D("THICKNESS", 0.0, ("any",), "Current thickness for new objects", "real")
D("ELEVATION", 0.0, ("any",), "Current elevation", "real")
D("INSBASE", [0.0, 0.0], ("point", "any"), "Drawing insertion base point", "point")
D("CONSTRAINTINFER", 0, TOGGLE, "Infer constraints while drawing")
D("FILLETRAD", 0.0, ("min", 0), "Fillet radius", "real")
D("CHAMFERA", 0.0, ("min", 0), "First chamfer distance", "real")
D("CHAMFERB", 0.0, ("min", 0), "Second chamfer distance", "real")
D("CHAMFERC", 0.0, ("min", 0), "Chamfer length", "real")
D("CHAMFERD", 0.0, ("any",), "Chamfer angle in degrees", "real", angle=True)
D("ACADVER", "AC1032", ("text",), "File version of the drawing", "string", hidden=False)

D("CENTEREXE", _pair(0.12, 3.5), ("min", 0), "Centre mark extension past circle", "real")
D("CHAMMODE", 0, TOGGLE, "Chamfer input: 0 distance-distance, 1 length-angle")
D("CIRCLERAD", 0.0, ("min", 0), "Default circle radius", "real")
D("CMLJUST", 0, ("set", (0, 1, 2)), "Multiline justification: 0 top, 1 middle, 2 bottom")
D("CMLSCALE", _pair(1.0, 20.0), ("any",), "Multiline scale", "real")
D("DIMASSOC", 2, ("set", (0, 1, 2)), "Dimension associativity")
D("DONUTID", 0.5, ("min", 0), "Donut inside diameter", "real")
D("DONUTOD", 1.0, ("gt", 0), "Donut outside diameter", "real")
D("EDGEMODE", 0, TOGGLE, "Trim and extend edge mode")
D("HPANG", 0.0, ("any",), "Hatch angle in degrees", "real", angle=True)
D("HPDLGMODE", 1, TOGGLE, "1 HATCH opens a dialog, 0 command line")
D("HPNAME", "ANSI31", ("text",), "Hatch pattern name", "string")
D("HPSCALE", 1.0, ("gt", 0), "Hatch scale", "real")
D("INSNAME", "", ("text",), "Default block name for INSERT", "string")
D("LWDEFAULT", 25, ("lw", False), "Default lineweight in hundredths of a millimetre")
D("OFFSETDIST", -1.0, ("any",), "Offset distance (negative means Through)", "real")
D("OFFSETERASE", 0, TOGGLE, "Erase source after offset")
D("OFFSETLAYER", 0, TOGGLE, "Layer of offset copies: 0 source layer, 1 current layer")
D("POLYSIDES", 4, ("range", 3, 1024), "Polygon side count")
D("PROJMODE", 1, ("range", 0, 2), "Projection mode for trim and extend")
D("REVCLOUDARCLEN", _pair(0.5, 15.0), ("gt", 0), "Revision cloud arc length", "real")
D("SPLINESEGS", 8, ("range", -32768, 32767), "Spline polyline segments")
D("SPLKNOTS", 0, ("range", 0, 2), "Spline knot parameterisation")
D("TEXTFILL", 1, TOGGLE, "Fill TrueType text in plots")
D("TRIMEXTENDMODE", 1, TOGGLE, "1 quick mode, 0 standard mode")
D("TRIMMODE", 1, TOGGLE, "Fillet and chamfer trim: 0 leave, 1 trim")
D("WIPEOUTFRAME", 1, ("range", 0, 2), "Wipeout frame: 0 hidden, 1 shown, 2 shown not plotted")
D("CMLSTYLE", "STANDARD", ("text",), "Current multiline style", "string")
D("PLINEWID", 0.0, ("min", 0), "Default polyline width", "real")
D("PLINEGEN", 0, TOGGLE, "Polyline linetype generation")
D("TRACEWID", _pair(0.05, 1.0), ("min", 0), "Default trace width", "real")
D("UCSNAME", "", ("text",), "Current coordinate system name", "string", hidden=True)

_DIM_TEXT = """DIMSCALE|Overall scale factor
DIMASZ|Arrow size
DIMEXO|Extension line offset from origin
DIMEXE|Extension line extension beyond dimension line
DIMTXT|Text height
DIMGAP|Gap between text and dimension line
DIMDEC|Decimal places
DIMADEC|Angular decimal places
DIMLFAC|Linear scale factor
DIMTAD|Text vertical position relative to the line
DIMTIH|Text inside extension lines is horizontal
DIMTOH|Text outside extension lines is horizontal
DIMBLK|Arrowhead block
DIMBLK1|First arrowhead block
DIMBLK2|Second arrowhead block
DIMTSZ|Tick size (replaces arrows when above zero)
DIMCLRD|Dimension line colour
DIMCLRE|Extension line colour
DIMCLRT|Text colour
DIMTFILL|Text background fill
DIMTFILLCLR|Text background fill colour
DIMTXSTY|Text style
DIMPOST|Prefix and suffix template
DIMCEN|Centre mark size
DIMZIN|Zero suppression
DIMLUNIT|Linear unit format
DIMTOL|Tolerance display
DIMTP|Plus tolerance
DIMTM|Minus tolerance
DIMDLI|Baseline spacing
DIMDLE|Dimension line extension
DIMJUST|Text justification along the line
DIMRND|Rounding increment
DIMDSEP|Decimal separator
DIMFRAC|Fraction format
DIMLIM|Limits display
DIMTDEC|Tolerance decimal places
DIMTFAC|Tolerance text height ratio
DIMTZIN|Tolerance zero suppression
DIMALT|Alternate units
DIMALTF|Alternate units multiplier
DIMALTD|Alternate units decimals
DIMAPOST|Alternate units template
DIMALTRND|Alternate units rounding
DIMALTU|Alternate units format
DIMALTZ|Alternate units zero suppression
DIMAUNIT|Angular unit format
DIMSE1|Suppress first extension line
DIMSE2|Suppress second extension line
DIMSD1|Suppress first dimension line half
DIMSD2|Suppress second dimension line half
DIMATFIT|Fit rule
DIMTIX|Force text inside
DIMSOXD|Suppress arrows that do not fit
DIMTOFL|Force a dimension line inside
DIMTMOVE|Text movement rule
DIMTVP|Vertical position offset
DIMTOLJ|Tolerance vertical justification
DIMAZIN|Angular zero suppression
DIMARCSYM|Arc symbol position
DIMLDRBLK|Leader arrowhead block
DIMLTYPE|Dimension line linetype
DIMLTEX1|First extension line linetype
DIMLTEX2|Second extension line linetype
DIMLWD|Dimension line lineweight
DIMLWE|Extension line lineweight
DIMFXLON|Fixed length extension lines
DIMFXL|Fixed extension line length
DIMJOGANG|Jog angle for jogged radius"""

_DIM_RULES = {
    "DIMSCALE": ("min", 0), "DIMASZ": ("min", 0), "DIMEXO": ("min", 0), "DIMEXE": ("min", 0), "DIMTXT": ("gt", 0), "DIMGAP": ("any",),
    "DIMDEC": ("range", 0, 8), "DIMADEC": ("range", 0, 8), "DIMTDEC": ("range", 0, 8), "DIMALTD": ("range", 0, 8),
    "DIMTAD": ("range", 0, 4), "DIMTIH": TOGGLE, "DIMTOH": TOGGLE, "DIMLUNIT": ("range", 1, 6), "DIMALTU": ("range", 1, 6),
    "DIMJUST": ("range", 0, 4), "DIMFRAC": ("range", 0, 2), "DIMATFIT": ("range", 0, 3), "DIMTMOVE": ("range", 0, 2),
    "DIMTOLJ": ("range", 0, 2), "DIMAUNIT": ("range", 0, 4), "DIMARCSYM": ("range", 0, 2), "DIMTFILL": ("range", 0, 2),
    "DIMTOL": TOGGLE, "DIMLIM": TOGGLE, "DIMALT": TOGGLE, "DIMSE1": TOGGLE, "DIMSE2": TOGGLE, "DIMSD1": TOGGLE, "DIMSD2": TOGGLE,
    "DIMTIX": TOGGLE, "DIMSOXD": TOGGLE, "DIMTOFL": TOGGLE, "DIMFXLON": TOGGLE, "DIMZIN": ("range", 0, 15), "DIMTZIN": ("range", 0, 15),
    "DIMALTZ": ("range", 0, 15), "DIMAZIN": ("range", 0, 3), "DIMLFAC": ("any",), "DIMFXL": ("min", 0), "DIMDLI": ("min", 0),
}

for _line in _DIM_TEXT.split("\n"):
    _n, _d = _line.split("|")
    _val = DIM_DEFAULTS[_n]
    _t = "string" if isinstance(_val, str) else ("real" if isinstance(_val, float) else "int")
    _rule = _DIM_RULES.get(_n, ("any",))
    VARS.append(VarDef(_n, _t, _val, "drawing", _rule, _d, dim=True, angle=(_n == "DIMJOGANG")))

BY_NAME: dict = {v.name: v for v in VARS}
LW_SET = frozenset(LINEWEIGHTS)


def drawing_defaults(metric: bool) -> dict:
    out = {}
    for v in VARS:
        if v.scope == "drawing" and not v.dim:
            out[v.name] = _copy_default(v.default_for(metric))
    return out


def _copy_default(d):
    return list(d) if isinstance(d, list) else d
