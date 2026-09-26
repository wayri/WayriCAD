"""Build the printable Constraint Studio layer-change user guide."""

from pathlib import Path

from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.utils import ImageReader
from reportlab.platypus import (
    HRFlowable, Image, KeepTogether, PageBreak, Paragraph, SimpleDocTemplate,
    Spacer, Table, TableStyle,
)


ROOT = Path(__file__).resolve().parents[1]
IMAGES = ROOT / "docs" / "guides" / "images"
OUTPUT = ROOT / "output" / "pdf" / "WayriCAD_Constraint_Studio_Layer_Change_Guide.pdf"
INK = colors.HexColor("#18303c")
TEAL = colors.HexColor("#17756d")
PALE = colors.HexColor("#e9f5f2")
MUTED = colors.HexColor("#526774")
LINE = colors.HexColor("#cbdadf")

styles = getSampleStyleSheet()
styles.add(ParagraphStyle(name="GuideTitle", fontName="Helvetica-Bold", fontSize=25, leading=29, textColor=INK, spaceAfter=13))
styles.add(ParagraphStyle(name="GuideH1", fontName="Helvetica-Bold", fontSize=16, leading=20, textColor=INK, spaceBefore=8, spaceAfter=8))
styles.add(ParagraphStyle(name="GuideH2", fontName="Helvetica-Bold", fontSize=11.2, leading=15, textColor=INK, spaceBefore=10, spaceAfter=5))
styles.add(ParagraphStyle(name="GuideBody", fontName="Helvetica", fontSize=9.2, leading=13.7, textColor=INK, spaceAfter=7))
styles.add(ParagraphStyle(name="GuideSmall", fontName="Helvetica", fontSize=7.8, leading=11, textColor=MUTED, spaceAfter=7))
styles.add(ParagraphStyle(name="GuideCaption", fontName="Helvetica-Oblique", fontSize=7.7, leading=10.5, textColor=MUTED, spaceBefore=4, spaceAfter=13))
styles.add(ParagraphStyle(name="GuideCallout", fontName="Helvetica", fontSize=9, leading=13, textColor=INK, backColor=PALE, borderPadding=10, borderColor=TEAL, borderWidth=.6, spaceBefore=8, spaceAfter=10))
styles.add(ParagraphStyle(name="GuideBullet", fontName="Helvetica", fontSize=9.2, leading=13.7, textColor=INK, leftIndent=16, firstLineIndent=-12, spaceAfter=5))
styles.add(ParagraphStyle(name="GuideEyebrow", fontName="Helvetica-Bold", fontSize=8, leading=12, textColor=TEAL, spaceAfter=9))


def p(text, style="GuideBody"):
    return Paragraph(text, styles[style])


def bullets(items):
    return [p(f"<b>{i}.</b> {item}", "GuideBullet") for i, item in enumerate(items, 1)]


def shot(name, caption, max_width=500, max_height=565):
    path = IMAGES / name
    width, height = ImageReader(str(path)).getSize()
    scale = min(max_width / width, max_height / height)
    return [Image(str(path), width=width * scale, height=height * scale), p(caption, "GuideCaption")]


def table(rows, widths):
    data = [[p(str(cell), "GuideSmall") for cell in row] for row in rows]
    out = Table(data, colWidths=widths, hAlign="LEFT", repeatRows=1)
    out.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), PALE),
        ("LINEBELOW", (0, 0), (-1, -1), .35, LINE),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 7),
        ("RIGHTPADDING", (0, 0), (-1, -1), 7),
        ("TOPPADDING", (0, 0), (-1, -1), 5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
    ]))
    return out


def footer(canvas, doc):
    canvas.saveState()
    w, _ = doc.pagesize
    canvas.setStrokeColor(LINE)
    canvas.line(48, 38, w - 48, 38)
    canvas.setFont("Helvetica", 7.5)
    canvas.setFillColor(MUTED)
    canvas.drawString(48, 26, "WayriCAD Constraint Studio  |  KiCad 10  |  24 September 2026")
    canvas.drawRightString(w - 48, 26, f"{doc.page}")
    canvas.restoreState()


def build():
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    doc = SimpleDocTemplate(str(OUTPUT), pagesize=(595.28, 841.89), rightMargin=48, leftMargin=48, topMargin=48, bottomMargin=51,
                            title="WayriCAD Constraint Studio - Automatic layer-change routing", author="WayriCAD")
    story = []
    story += [p("WAYRICAD / CONSTRAINT STUDIO / KICAD 10", "GuideEyebrow"),
              p("Automatic layer-change routing", "GuideTitle"),
              p("A step-by-step guide to assigning track width and differential-pair gap by copper layer, applying a reviewed profile, and routing with Constraint Studio closed."),
              Spacer(1, 18),
              p("What changes automatically?", "GuideH1"),
              p("After the review is applied and the project is reopened, KiCad chooses the saved width and pair gap when a <b>new</b> route starts on each configured layer. Studio is not a background routing hook."),
              p("Save board  &gt;  Set profile  &gt;  Stage and export  &gt;  Apply and reopen  &gt;  Route", "GuideCallout"),
              p("<b>At a transition via:</b> KiCad 10 keeps one width during an active route. Finish at the via, start a new route on the destination layer, and turn <b>Auto track width off</b>. Otherwise KiCad can inherit the previous segment's width.", "GuideCallout"),
              p("All dimensions shown in the screenshots are illustrative. Use values approved for your actual stackup and fabricator.", "GuideSmall"),
              Spacer(1, 16), HRFlowable(width="100%", color=LINE), Spacer(1, 12),
              p("1  Save the board and physical stackup", "GuideH1")]
    story += bullets([
        "Open the project in KiCad PCB Editor. Verify enabled copper layers, dielectrics and copper thicknesses in <b>Board Setup</b>.",
        "Save Board Setup and the PCB. Confirm the nets to be routed are present in the saved board.",
        "Open <b>Tools &gt; External Plugins &gt; WayriCAD Constraint Studio</b>. If the board changed while Studio was open, return to a clean workspace or use <b>Reload saved board</b>. Export or undo staged edits first.",
    ])
    story += [p("Check: Physical stackup shows the expected layers. A missing net usually indicates a stale saved snapshot or a net not yet present on the PCB.", "GuideCallout"), PageBreak(),
              p("2  Create a profile for each protocol instance", "GuideH1")]
    story += bullets([
        "Open <b>Layer routing profiles</b> and choose <b>New profile</b> or <b>+ New protocol</b> (label varies by build).",
        "Name the specific bus, such as CAN1. Choose its protocol family and <b>Signal type</b>.",
        "Under <b>Apply to</b>, choose selected nets/group or an existing netclass. Search and tick exact saved-board nets. For a pair, include both members, for example CAN_P and CAN_N. The family label alone does not create a KiCad pair.",
        "Create separate tabs for CAN2, Ethernet ports or DDR groups with different geometry. Duplicate copies geometry but clears the net selection.",
    ])
    story += shot("layer-routing-overview.png", "Figure 1. Source-derived rendering of the shipped interface, using demonstration values. It is not a PCB Editor screenshot.", max_height=490)
    story += [PageBreak(), p("Select the exact nets", "GuideH2")]
    story += shot("layer-routing-net-selection.png", "Figure 2. User-provided Constraint Studio screenshot. If the list says 'No matching nets,' reload the saved board before staging.", max_height=330)
    story += [p("3  Enter geometry for every permitted layer", "GuideH1")]
    story += bullets([
        "Click <b>+ Signal layer</b> for each copper layer this group may use. Select the signal layer and its actual reference plane or planes.",
        "Enter <b>Width mm</b> and, for a pair, <b>Pair gap mm</b> on each row. The pair gap is edge-to-edge. Use verified stackup or fabricator values; Estimate width is only a screening approximation at a fixed gap.",
        "Compare the shared-scale <b>Layer previews</b>. Trace, Pair and Trace + pair modes should update visibly as dimensions change.",
        "Optionally <b>Prohibit tracks on unconfigured layers</b>. This policy does not prohibit vias.",
    ])
    story += [table([["Illustrative layer", "Width", "Pair gap", "New route uses"], ["F.Cu", "0.20 mm", "0.18 mm", "Front-layer geometry"], ["B.Cu", "0.30 mm", "0.25 mm", "Back-layer geometry"]], [110, 85, 85, 219]), PageBreak(),
              p("Compare the layer previews", "GuideH2")]
    story += shot("layer-routing-preview.png", "Figure 3. User-provided shared-scale layer preview. It illustrates geometry; it does not calculate impedance or alter PCB copper.", max_height=385)
    story += [p("Reference-plane check: A named copper layer does not prove an unbroken return plane. Inspect continuity, plane voids and the return path at each via.", "GuideCallout"),
              p("4  Review the optional via recipe", "GuideH1"),
              p("If the bus needs a particular via, choose through, microvia, blind or buried type, copper diameter and drill. Set a valid start/end copper-layer span for a non-through via. <b>Use saved sizes</b> copies netclass dimensions for review. Board Setup must permit the via type and the recipe must meet manufacturing floors."),
              p("Studio stages scoped DRC limits for the recipe. KiCad's tuning profile does <b>not</b> automatically switch the router's via type; select it in PCB Editor.", "GuideCallout"), PageBreak(),
              p("5  Stage, review, export and apply", "GuideH1")]
    story += bullets([
        "Click <b>Review &amp; stage profile</b>. Resolve missing nets, overlapping assignments, stale stackup and invalid dimensions.",
        "In <b>Review &amp; export</b>, inspect Local findings, File diff and Native rules. Export to a new empty folder, then run native KiCad DRC on that exported snapshot.",
        "Click <b>Open Apply Review</b>. Close every source-project KiCad editor before confirming the helper's write. Review its file list; it checks fingerprints and creates backups.",
        "Reopen the project in PCB Editor. The profile persists with Studio closed. If the stackup changes, reopen Studio and restage.",
    ])
    story += [p("Stage alone changes only the Studio workspace. The open PCB Editor does not receive the new rules until the reviewed export is applied and the project is reopened.", "GuideCallout"),
              p("6  Route from one layer to another", "GuideH1")]
    story += bullets([
        "Use KiCad <b>netclass/rule-driven sizing</b> for tracks or pairs. Clear explicit manual width/gap overrides. Turn <b>Auto track width off</b>.",
        "Start a new route on the first configured layer and inspect KiCad's width and, for a pair, gap.",
        "Place the permitted transition via, then <b>finish the active route at the via</b>.",
        "Switch layers and start a <b>new</b> route from the via. Inspect the destination layer's width and gap. Repeat for every transition.",
        "Save the PCB, run native DRC, and review each pair member and return-path transition.",
    ])
    story += [p("Illustration only: a new F.Cu route may use 0.20 mm width / 0.18 mm pair gap, and a new B.Cu route may use 0.30 mm / 0.25 mm after restarting at the via.", "GuideCallout"), PageBreak(),
              p("Verify that the profile is working", "GuideH1")]
    story += [p("- Start a new route on every configured layer and inspect the chosen width and gap.<br/>- Close and reopen the project, then repeat with Studio closed to confirm persistence.<br/>- Inspect saved track properties and run DRC. Existing copper is not resized.<br/>- Test a net from each CAN, Ethernet or DDR instance; new net names are not silently included.")]
    story += [p("The recorded KiCad 10.0.6 single-track check measured 0.20 mm on F.Cu and 0.30 mm on B.Cu after a route restart with Auto track width off. The user subsequently confirmed differential-pair layer routing in their session; the repository has no measured route capture for that pair test.", "GuideSmall"),
              p("If a size does not change", "GuideH1"),
              table([
                  ["Symptom", "Check"],
                  ["Net list empty or stale", "Save the PCB, return to a clean Studio workspace and Reload saved board. Confirm both pair nets exist on the PCB."],
                  ["New layer keeps old width", "Turn Auto track width off; finish at the via and start a new route. Clear manual overrides."],
                  ["Wrong pair gap", "Check KiCad-recognized pair names, both selected members, destination-layer gap row and higher-priority scoped rules."],
                  ["Wrong via type", "Select the type in the router. Studio's via recipe is a DRC constraint, not automatic selection."],
                  ["Changes absent after Stage", "Export and apply the review with source editors closed, then reopen the project."],
                  ["Profile marked stale", "Review the changed saved stackup or owned rules and restage."],
              ], [147, 352]),
              Spacer(1, 13),
              p("Screenshot provenance: Figure 1 is a source-derived UI rendering with demo data. Figures 2-3 are user-provided Constraint Studio captures. None is a fabrication or impedance sign-off.", "GuideSmall")]
    doc.build(story, onFirstPage=footer, onLaterPages=footer)
    print(OUTPUT)


if __name__ == "__main__":
    build()
