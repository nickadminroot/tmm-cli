"""Focused probe using the documented API5 ksTextEx representation.

The critical detail from ASCON lesson 15: composite item kinds are assigned to
TextItemFont.bitVector, not TextItemParam.type.  type/iSNumb are only used for
FRACTION_TYPE, SUM_TYPE and SPECIAL_SYMBOL.
"""
from __future__ import annotations
import json, os
from pathlib import Path
from probe_kompas_api5_control_syntax import connect, export_png, readback, qi

# ksTextItemEnum / ldefin2d.h values, confirmed in current API7 constants.
NUMERATOR, DENOMINATOR, END_FRACTION = 1, 2, 3
UPPER, LOWER, END_DEVIAT = 4, 5, 6
S_BASE, S_UPPER, S_LOWER, S_END = 7, 8, 9, 16
SPECIAL, SPECIAL_END = 17, 18
FRACTION_TYPE = 1  # candidate; tested separately below


def item(raw5, const, text, bit=0, item_type=0, i_s_numb=0, height=10.0, symbol=False):
    x = raw5.GetParamStruct(const.ko_TextItemParam)
    x.Init(); x.s = text; x.type = item_type; x.iSNumb = i_s_numb
    f = x.GetItemFont(); f.fontName = "Symbol type A" if symbol else "GOST type A"
    f.height = height; f.ksu = 1; f.color = 0; f.bitVector = bit
    x.SetItemFont(f)
    return x


def param(raw5, const, x, y, specs, height=10.0):
    tp = raw5.GetParamStruct(const.ko_TextParam); tp.Init()
    pp = raw5.GetParamStruct(const.ko_ParagraphParam); pp.Init()
    pp.x, pp.y, pp.height, pp.width = x, y, height, 120.0
    pp.ang, pp.hFormat, pp.vFormat = 0, 0, 0; tp.SetParagraphParam(pp)
    lp = raw5.GetParamStruct(const.ko_TextLineParam); lp.Init()
    arr = lp.GetTextItemArr(); arr.ksClearArray()
    for spec in specs: arr.ksAddArrayItem(-1, item(raw5, const, *spec, height=height))
    lp.SetTextItemArr(arr); lines = tp.GetTextLineArr(); lines.ksClearArray()
    lines.ksAddArrayItem(-1, lp); tp.SetTextLineArr(lines)
    return tp


def main():
    out = Path(os.path.join(os.environ.get("TEMP", "."), "tmm-scene-kompas-correct-bitvectors")).absolute(); out.mkdir(parents=True, exist_ok=True)
    m7,m5,const,app,doc,doc2d,raw5 = connect(); evidence=[]
    cases = [
      ("script_correct", 20, 220, [("F",S_BASE,0,0), ("t",S_UPPER,0,0), ("32",S_LOWER,0,0), ("",S_END,0,0)]),
      ("fraction_correct", 20, 185, [("A",0,0,0), ("1",NUMERATOR,0,0), ("2",DENOMINATOR,0,0), ("B",END_FRACTION,0,0)]),
      ("deviation_correct", 20, 150, [("D",0,0,0), ("+0.1",UPPER,0,0), ("-0.2",LOWER,0,0), ("",END_DEVIAT,0,0)]),
      ("special_overline_correct", 20, 115, [("abc",SPECIAL,17,95), ("",SPECIAL_END,0,0)]),
      ("special_underline_correct", 20, 80, [("abc",SPECIAL,17,96), ("",SPECIAL_END,0,0)]),
      ("special_overline_fraction_inline", 100, 115, [("$d1;2$",SPECIAL,17,95), ("",SPECIAL_END,0,0)]),
      ("special_underline_script_inline", 180, 115, [("F$t;32$",SPECIAL,17,96), ("",SPECIAL_END,0,0)]),
      ("special_overline_fraction", 100, 80, [("",SPECIAL,0,95), ("1",NUMERATOR,0,0), ("2",DENOMINATOR,0,0), ("",END_FRACTION,0,0), ("",SPECIAL_END,0,0)]),
      ("special80_next_down", 20, 45, [("B",SPECIAL,0,80), ("UP",0x13,0,0), ("DN",0x14,0,0), ("",SPECIAL_END,0,0)]),
      ("special80_next_right", 100, 45, [("B",SPECIAL,0,80), ("UP",0x13,0,0), ("DN",0x15,0,0), ("",SPECIAL_END,0,0)]),
      ("special_underline_script", 180, 115, [("",SPECIAL,0,96), ("F",S_BASE,0,0), ("t",S_UPPER,0,0), ("32",S_LOWER,0,0), ("",S_END,0,0), ("",SPECIAL_END,0,0)]),
      ("fraction_type_candidate", 100, 185, [("A",0,0,0), ("1",0, FRACTION_TYPE,3), ("2",DENOMINATOR,0,0), ("B",END_FRACTION,0,0)]),
    ]
    for label,x,y,specs in cases:
        try:
            ref=doc2d.ksTextEx(param(raw5,const,x,y,specs),0); evidence.append({"label":label,"ref":ref})
        except Exception as e: evidence.append({"label":label,"error":str(e)})
    path=out/'correct-bitvectors.cdw'; png=out/'correct-bitvectors.png'; doc.SaveAs(str(path)); export_png(m7,doc,png)
    result={'evidence':evidence,'readback':readback(m7,doc),'cdw':str(path),'png':str(png)}
    (out/'correct-bitvectors.json').write_text(json.dumps(result,ensure_ascii=False,indent=2,default=str),encoding='utf8')
    print(json.dumps(result,ensure_ascii=False,indent=2,default=str)); doc.Close(False)

if __name__=='__main__': main()
