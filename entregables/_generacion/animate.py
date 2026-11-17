"""Inject entrance animations and slide transitions into a pptxgenjs deck.

Shapes are tagged by the generator with names ``aNN_<effect>_<k>``. Each group NN plays in order
(after the previous group, starting automatically when the slide appears); shapes of the same
group play together. Effects: fade, zoom (fade + zoom), wipe (wipe from left).
"""
import re
import sys
import zipfile
from collections import defaultdict

SRC, DST = sys.argv[1], sys.argv[2]
DUR = {"fade": 450, "zoom": 500, "wipe": 600}
STAGGER = 120  # ms between groups beyond the effect duration overlap


class Ids:
    def __init__(self):
        self.n = 2

    def next(self):
        self.n += 1
        return self.n


def effect_xml(ids, spid, eff, node_type, is_text):
    dur = DUR[eff]
    set_vis = (
        f'<p:set><p:cBhvr><p:cTn id="{ids.next()}" dur="1" fill="hold"><p:stCondLst><p:cond delay="0"/></p:stCondLst></p:cTn>'
        f'<p:tgtEl><p:spTgt spid="{spid}"/></p:tgtEl><p:attrNameLst><p:attrName>style.visibility</p:attrName></p:attrNameLst></p:cBhvr>'
        f'<p:to><p:strVal val="visible"/></p:to></p:set>'
    )
    if eff == "fade":
        preset, sub = 10, 0
        body = set_vis + (f'<p:animEffect transition="in" filter="fade"><p:cBhvr><p:cTn id="{ids.next()}" dur="{dur}"/>'
                          f'<p:tgtEl><p:spTgt spid="{spid}"/></p:tgtEl></p:cBhvr></p:animEffect>')
    elif eff == "wipe":
        preset, sub = 22, 8
        body = set_vis + (f'<p:animEffect transition="in" filter="wipe(left)"><p:cBhvr><p:cTn id="{ids.next()}" dur="{dur}"/>'
                          f'<p:tgtEl><p:spTgt spid="{spid}"/></p:tgtEl></p:cBhvr></p:animEffect>')
    else:  # zoom: "Zoom" entrance (fade + scale)
        preset, sub = 53, 16
        body = set_vis + (
            f'<p:anim calcmode="lin" valueType="num"><p:cBhvr><p:cTn id="{ids.next()}" dur="{dur}" fill="hold"/>'
            f'<p:tgtEl><p:spTgt spid="{spid}"/></p:tgtEl><p:attrNameLst><p:attrName>ppt_w</p:attrName></p:attrNameLst></p:cBhvr>'
            f'<p:tavLst><p:tav tm="0"><p:val><p:fltVal val="0"/></p:val></p:tav><p:tav tm="100000"><p:val><p:strVal val="#ppt_w"/></p:val></p:tav></p:tavLst></p:anim>'
            f'<p:anim calcmode="lin" valueType="num"><p:cBhvr><p:cTn id="{ids.next()}" dur="{dur}" fill="hold"/>'
            f'<p:tgtEl><p:spTgt spid="{spid}"/></p:tgtEl><p:attrNameLst><p:attrName>ppt_h</p:attrName></p:attrNameLst></p:cBhvr>'
            f'<p:tavLst><p:tav tm="0"><p:val><p:fltVal val="0"/></p:val></p:tav><p:tav tm="100000"><p:val><p:strVal val="#ppt_h"/></p:val></p:tav></p:tavLst></p:anim>'
            f'<p:animEffect transition="in" filter="fade"><p:cBhvr><p:cTn id="{ids.next()}" dur="{dur}"/>'
            f'<p:tgtEl><p:spTgt spid="{spid}"/></p:tgtEl></p:cBhvr></p:animEffect>'
        )
    grp = ' grpId="0"'
    return (f'<p:par><p:cTn id="{ids.next()}" presetID="{preset}" presetClass="entr" presetSubtype="{sub}" fill="hold"{grp} nodeType="{node_type}">'
            f'<p:stCondLst><p:cond delay="0"/></p:stCondLst><p:childTnLst>{body}</p:childTnLst></p:cTn></p:par>')


def timing_xml(groups, text_ids):
    ids = Ids()
    outer = ids.next()  # 3
    inner_pars = []
    t = 0
    for g in sorted(groups):
        members = groups[g]
        effs = []
        for k, (spid, eff) in enumerate(members):
            effs.append(effect_xml(ids, spid, eff, "afterEffect" if k == 0 else "withEffect", spid in text_ids))
        inner_pars.append(f'<p:par><p:cTn id="{ids.next()}" fill="hold"><p:stCondLst><p:cond delay="{t}"/></p:stCondLst>'
                          f'<p:childTnLst>{"".join(effs)}</p:childTnLst></p:cTn></p:par>')
        t += max(DUR[e] for _, e in members) - 250 + STAGGER
    bld = "".join(f'<p:bldP spid="{s}" grpId="0" animBg="1"/>' for s in sorted({s for m in groups.values() for s, _ in m} & text_ids, key=int))
    return ('<p:timing><p:tnLst><p:par><p:cTn id="1" dur="indefinite" restart="never" nodeType="tmRoot"><p:childTnLst>'
            '<p:seq concurrent="1" nextAc="seek"><p:cTn id="2" dur="indefinite" nodeType="mainSeq"><p:childTnLst>'
            f'<p:par><p:cTn id="{outer}" fill="hold"><p:stCondLst><p:cond delay="indefinite"/><p:cond evt="onBegin" delay="0"><p:tn val="2"/></p:cond></p:stCondLst>'
            f'<p:childTnLst>{"".join(inner_pars)}</p:childTnLst></p:cTn></p:par>'
            '</p:childTnLst></p:cTn><p:prevCondLst><p:cond evt="onPrev" delay="0"><p:tgtEl><p:sldTgt/></p:tgtEl></p:cond></p:prevCondLst>'
            '<p:nextCondLst><p:cond evt="onNext" delay="0"><p:tgtEl><p:sldTgt/></p:tgtEl></p:cond></p:nextCondLst></p:seq>'
            f'</p:childTnLst></p:cTn></p:par></p:tnLst>{"<p:bldLst>" + bld + "</p:bldLst>" if bld else ""}</p:timing>')


NAME_RE = re.compile(r'<p:cNvPr id="(\d+)" name="(a(\d\d)_(fade|zoom|wipe)_\d+[^"]*)"')
stats = {}
zin = zipfile.ZipFile(SRC)
zout = zipfile.ZipFile(DST, "w", zipfile.ZIP_DEFLATED)
for item in zin.infolist():
    data = zin.read(item.filename)
    m = re.fullmatch(r"ppt/slides/slide(\d+)\.xml", item.filename)
    if m:
        xml = data.decode("utf-8")
        groups = defaultdict(list)
        text_ids = set()
        for sp in re.finditer(r"<p:sp>.*?</p:sp>", xml, re.S):
            mm = NAME_RE.search(sp.group(0))
            if mm and "<p:txBody>" in sp.group(0) and "<a:t>" in sp.group(0):
                text_ids.add(mm.group(1))
        for mm in NAME_RE.finditer(xml):
            groups[int(mm.group(3))].append((mm.group(1), mm.group(4)))
        n = int(m.group(1))
        trans = '<p:transition spd="med"><p:fade/></p:transition>'
        if "<p:timing" in xml or "<p:transition" in xml:
            raise SystemExit(f"slide {n} already has timing/transition")
        insert = trans + (timing_xml(groups, text_ids) if groups else "")
        if "</p:clrMapOvr>" in xml:
            xml = xml.replace("</p:clrMapOvr>", "</p:clrMapOvr>" + insert, 1)
        else:
            xml = xml.replace("</p:cSld>", "</p:cSld>" + insert, 1)
        stats[n] = (len(groups), sum(len(v) for v in groups.values()))
        data = xml.encode("utf-8")
    zout.writestr(item, data)
zout.close()
for n in sorted(stats):
    print(f"slide {n}: {stats[n][0]} pasos de animación, {stats[n][1]} objetos animados")
