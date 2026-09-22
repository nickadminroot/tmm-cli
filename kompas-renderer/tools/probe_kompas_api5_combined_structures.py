"""Probe combining KOMPAS upper/lower text (S_* flags) and index syntax.

Goal: reproduce XML te_md_updn_* and te_md_supsub_* in one DrawingText.
No clipboard and no geometry.
"""
from __future__ import annotations
import json, os
from pathlib import Path
from probe_kompas_api5_control_syntax import connect, export_png, readback
from probe_kompas_api5_correct_bitvectors import param

S_BASE, S_UPPER, S_LOWER, S_END = 7, 8, 9, 16

def main():
    out=Path(os.path.join(os.environ.get("TEMP", "."), "tmm-scene-kompas-combined-structures")).absolute();out.mkdir(parents=True,exist_ok=True)
    m7,m5,const,app,doc,doc2d,raw5=connect(); cases=[
      ("updn_plain", 20, 220, [("F",S_BASE,0,0),("UP",S_UPPER,0,0),("DN",S_LOWER,0,0),("",S_END,0,0)]),
      ("updn_base_contains_index", 20, 170, [("F$t;32$",S_BASE,0,0),("UP",S_UPPER,0,0),("DN",S_LOWER,0,0),("",S_END,0,0)]),
      ("updn_upper_contains_index", 100, 170, [("F",S_BASE,0,0),("U$2;3$",S_UPPER,0,0),("DN",S_LOWER,0,0),("",S_END,0,0)]),
      ("updn_lower_contains_index", 180, 170, [("F",S_BASE,0,0),("UP",S_UPPER,0,0),("L$2;3$",S_LOWER,0,0),("",S_END,0,0)]),
      ("updn_nested_both", 20, 110, [("F$t;32$",S_BASE,0,0),("U$2;3$",S_UPPER,0,0),("L$4;5$",S_LOWER,0,0),("",S_END,0,0)]),
    ]; evidence=[]
    for label,x,y,specs in cases:
      try: evidence.append({"label":label,"ref":doc2d.ksTextEx(param(raw5,const,x,y,specs),0)})
      except Exception as e: evidence.append({"label":label,"error":str(e)})
    cdw=out/'combined.cdw';png=out/'combined.png';doc.SaveAs(str(cdw));export_png(m7,doc,png)
    result={"evidence":evidence,"readback":readback(m7,doc),"cdw":str(cdw),"png":str(png)}
    (out/'combined.json').write_text(json.dumps(result,ensure_ascii=False,indent=2,default=str),encoding='utf8');print(json.dumps(result,ensure_ascii=False,indent=2,default=str));doc.Close(False)
if __name__=='__main__':main()
