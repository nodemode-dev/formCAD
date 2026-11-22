# Command catalogue by registry group

Generated from the live registry; names marked with a star have no programmatic form or are barred to outside agents (use the FormCAD window). Regenerate the live tool list with scripts/list_tools.py, which is authoritative.

Counts when generated: 727 commands, 693 MCP tools (23 fixed formcad_ tools plus cmd_[id] tools), 40 in the core set. Added by hand in 0.26.0: imageattach and pdfattach (block), imageclip, pdfclip, imageadjust and pdfadjust (modify). Added by hand in 0.27.0: gcmidpoint (constraints). Costing, DFM, design check and sustainability have no commands or MCP tools: they are engine routes only (see sub-skills/manufacture).

## Contents

- additive
- annotate
- annotation
- automation
- block
- constraints
- draw
- edit
- extra
- file
- format
- harness
- inquiry
- layout
- lisp
- macro
- modify
- output
- script
- settings
- solids
- toolbox
- tools
- vault
- view

## additive

additiveexport

## annotate

-dimstyle dim dimaligned dimangular dimarc dimbaseline dimbreak dimcenter dimcontinue dimdiameter dimdisassociate dimedit dimedit.oblique diminspect dimjogged dimjogline dimlinear dimordinate dimoverride dimradius dimreassociate dimregen dimspace dimstyle dimstyle.compare* dimstyle.current* dimstyle.delete* dimstyle.dimension dimstyle.list* dimstyle.override* dimstyle.rename* dimstyle.update dimtedit dimtedit.angle dimtedit.center dimtedit.home dimtedit.left dimtedit.right qdim

## annotation

aiobjectscaleadd aiobjectscaleremove annoreset annotationvisibility annoupdate autoballoon balloon bomtable bomupdate centermark centermarks datalink datalinkupdate datumsym finishmark gdtedit gdtframe leader mleader mleaderalign mleadercollect mleaderedit mleaderedit.add* mleaderedit.remove* modelitems objectscale scalelistedit sectionhatch table table.align table.border table.cellstyle table.colwidth table.deletecolumn table.deleterow table.fill table.format table.formula table.insertcolumn table.insertrow table.merge table.recalc table.rowheight table.setcell table.textheight table.unmerge tablebreak tabledit tableexport titleblock viewdim weldcuttable weldcutupdate

## automation

pluginenable* plugins

## block

-xref bclose bdescription bedit bsave bsaveas dynblock.define dynblock.drag dynblock.grips dynblock.props dynblock.read dynblock.set imageattach pdfattach refclose refedit refset xattach xbind xclip xopen xref

## constraints

autoconstrain constraintbar constraintinfer constraintsettings constraintstatus dcaligned dcangular dcdiameter dcdisplay dchorizontal dclinear dcradius dcvertical delconstraint dimconstraint gccoincident gccollinear gcconcentric gcequal gcfix gchorizontal gcmidpoint gcparallel gcperpendicular gcsmooth gcsymmetric gctangent gcvertical geomconstraint parameters parametersclose sketch sketchstatus

## draw

-attdef -block -hatch -insert 3dpoly arc arc.continue* arc.csa* arc.cse* arc.csl* arc.sca* arc.sce* arc.scl* arc.sea* arc.sed* arc.ser* attdef base block blocks.list blockspalette boundary centerline circle circle.2p* circle.3p* circle.cd* circle.ttr circle.ttt crv crvblend crvinterp divide donut ellipse ellipse.arc ellipse.axis gradient hatch hatch.patterns hatchpick helix insert line measure mline mtext pline point point.multiple polygon ray rectang region revcloud revcloud.freehand revcloud.polygonal solid spline spline.cv text wipeout xline

## edit

find mredo* qselect redo u undo

## extra

breakline

## file

-purge -wblock audit close closeall compare compareclose compareexport comparenext compareprevious dataextraction drawingrecovery export import new open purge qnew qnewtemplate recover save saveas wblock

## format

-layer* -linetype -style -units color copytolayer ddptype laycur laydel layer layer.apply layer.current layer.delete layer.filter layer.list layer.merge layer.new layer.rename layer.set layer.state layerp layerstate* layfrz layiso laylck laymch laymcur laymrg layoff layon laythw layulk layuniso laywalk limits linetype ltscale lweight mleaderstyle mlstyle rename style style.current style.delete style.list style.rename tablestyle thickness units

## harness

harness harnessexport

## inquiry

analysisoff analyzeshapes analyzeusage angle.measure bodymass cal count countlist counttable crvcont curvatureanalysis curvaturecomb deviation dist* draftanalysis id* impliedloops inspectdrawing list massprop measuregeom nakededges queryentities querytexts quickcalc.pick radius.measure seamcheck status surfreport time volume.measure wallthickness weldcutlist zebra

## layout

layout layout.copy layout.delete layout.list layout.move layout.new layout.rename layout.saveas layout.set layout.template mspace mview pagesetup pspace viewaux viewbase viewbroken viewcrop viewdelete viewdetail viewedit viewport.list viewport.set viewprojected viewprojection viewsection viewupdate vpclip vplayer vpmax vpmin

## lisp

appload* lisp

## macro

lispconsole macroplay* macrorecord macrorecorder macrosave* macrostop

## modify

-array -attedit align array arrayclose arrayedit arraypath arraypath.simple arraypolar arrayrect attedit attsync battman blend block.description blockreplace break breakatpoint burst chamfer change chprop chspace copy crvdegree crvextend crvfit crvknot crvmatch crvoffset crvperiodic crvrebuild crvreverse crvsimplify crvsub erase explode extend fillet flatten gumball hatchedit imageadjust imageclip intersect join lengthen matchprop mirror mledit mocoro move ncopy offset oops pdfadjust pdfclip pedit properties properties.set reverse rotate scale select* selectall* splinedit stretch subtract textedit trim union

## output

-plot bomexport exportpdf plot plotstyle plottermanager pngout preview publish stylesmanager svgout

## script

delay resume rscript script

## settings

aliasedit* asmsearch* docprops* dsettings dynmode gdtstyle* getvar* grid isodraft isoplane lwdisplay materiallib* matesettings* modeltol* motionsettings* ortho osnap otrack polar qpmode reinit* selectioncycling setvar snap sysvars* transparencydisplay

## solids

arrangeplate asmbom asmconfig asmembed asmfind asmflags asminsert asmmove asmpattern asmrebase asmrefresh asmreload asmremove asmreplace blendedge boardstep* boolcheck boolop box camdelete camexport camgenerate cammachine camnest camnestexport camop camprobe camprocess camsetup camtime camtool camturnprofile chamferedge combine cone config contactset cylinder designtable drillexport* dynamics ecaderc ecadpush* ecadsync* explodeview extrude featadd featcut featdelete featedit featextrude featforcerebuild featrebuild featrevolve featrevolvecut featrollback featsuppress featunsuppress features filletedge flatexport flatpattern genapply genrun gerberexport* idfexport* info3dm interfere interferesweep joint jointdelete jointdrive jointedit jointlink jointlinkdelete mate matedelete matedrag matedrive mateedit material matesolve matestatus meshboolean meshfill meshfromsolid meshintersect meshnaked meshreduce meshremesh meshrepair meshreport meshsection meshselfx meshsubtract meshtobrep meshunify meshunion meshweld moldblock moldclear molddraft moldparting moldsettings moldsplit motionstudy movecopybody orientstudy partauto partprops partsketch partsketchdone partworkspace pcbdrc pipebender pipecutlist pipeexport pipefitting piperoute pipespec plasticboss plasticcheck plasticgroove plasticlip plasticrib plasticrule pmidatum pmidelete pmidim pmiedit pmitol refgeo schemdevice schemdraw schemexport schemnumber schemwire schemwirelist simcontact simcontrol simfixture simload simmaterial simprobe simreport simrun simstudy slice smbaseflange smbendrelief smbends smcheck smconvert smcornerrelief smedgeflange smhem smjog smmiterflange smrule smsketchbend smtable snaphook solidmove sphere splitbody srfblend srfedge srfextend srfextrude srfjoin srfloft srfmatch srfnetwork srfoffset srfpatch srfplanar srfrevolve srfsplit srfsweep srftrim subdbox subdbridge subdconvert subdcrease subdcylinder subddelete subddisplay subddivideface subdextrude subdfillhole subdinfo subdinsertedge subdmove subdplane subdquadball subdrevolve subdrotate subdscale subdsphere subdsymmetry subdtorus subduncrease topoapply toporun toposhape torus weldendcap weldframe weldgusset weldjoint weldmember

## toolbox

inspection inspectionexport mbdview toolboximport toolboxinsert

## tools

-group analysisramp* graph* graphbake graphexport graphimport graphrun group groupedit groups.list pickstyle ungroup

## vault

vaultbranch vaultcheckin vaultcheckout vaultcomment vaultcreate* vaultdiff vaultgc* vaultlock* vaultlog vaultmerge vaultpin* vaultrevise* vaultstate* vaulttag vaultundo vaultverify vaultwhereused

## view

-view -vports attdisp pan redraw regen regenall view vports zoom
