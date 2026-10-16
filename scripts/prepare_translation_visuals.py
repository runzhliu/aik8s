#!/usr/bin/env python3
"""Create a local SVG typography workbench; measurements use the browser's fonts."""
import html
import json
import re

from bilingual import ROOT, digest
from translate_assets import ASSET_MAP, localize_asset

records = json.loads(ASSET_MAP.read_text())
cards = []
for index, (name, record) in enumerate(records.items()):
    if not name.endswith('.svg'):
        continue
    svg = localize_asset(ROOT / 'docs' / name, record, use_layout=False)
    identifier = f'visual-qa-{index}'
    svg = svg.replace('<svg ', f'<svg id="{identifier}" ', 1)
    # Inline SVG styles otherwise leak between figures in this preview gallery.
    def scoped_style(match):
        css = re.sub(r'([^{}]+)\{', lambda m: ','.join('#'+identifier+' '+selector.strip() for selector in m.group(1).split(','))+'{', match.group(1))
        return '<style>' + css + '</style>'
    svg = re.sub(r'<style>(.*?)</style>', scoped_style, svg, flags=re.S)
    changed = set(record['strings'].values())
    svg = re.sub(r'<text\b([^>]*)>([^<]*)</text>', lambda m: '<text'+m.group(1)+(' data-translated-label="true"' if html.unescape(m.group(2)) in changed else '')+'>'+m.group(2)+'</text>', svg)
    label_hash = digest(json.dumps(record['strings'], ensure_ascii=False, sort_keys=True))
    cards.append(f'<section data-name="{html.escape(name)}" data-source="{record["source_sha256"]}" data-labels="{label_hash}"><h2>{html.escape(name)}</h2>{svg}</section>')

script = r'''
const sections = Array.from(document.querySelectorAll('section'));
const number = (node, key, fallback=0) => parseFloat(node.getAttribute(key) || fallback);
function fit() {
  const failures = [];
  for (const section of sections) {
    const svg=section.querySelector('svg'), full=svg.viewBox.baseVal;
    const all=Array.from(svg.querySelectorAll('text'));
    const rects=Array.from(svg.querySelectorAll('rect')).map(r=>({x:number(r,'x'),y:number(r,'y'),w:number(r,'width'),h:number(r,'height')})).filter(r=>r.w>35&&r.h>20);
    for (const text of all) {
      if(text.querySelector('tspan')||!text.hasAttribute('data-translated-label')||/rotate/.test(text.getAttribute('transform')||'')) continue;
      const original=text.textContent, originalSize=parseFloat(getComputedStyle(text).fontSize);
      const x=number(text,'x'),y=number(text,'y'), anchor=getComputedStyle(text).textAnchor||'start';
      const containers=rects.filter(r=>x>=r.x&&x<=r.x+r.w&&y>=r.y&&y<=r.y+r.h).sort((a,b)=>a.w*a.h-b.w*b.h);
      const box=containers[0]||{x:0,y:0,w:full.width,h:full.height};
      const available=anchor==='middle'?2*Math.min(x-box.x,box.x+box.w-x)-24:anchor==='end'?x-box.x-16:box.x+box.w-x-16;
      const limit=Math.min(number(text,'data-max-width',available),available);
      if(limit<20||text.getComputedTextLength()<=limit) continue;
      const minimum=Math.max(14,originalSize*.78), ratio=limit/text.getComputedTextLength();
      text.setAttribute('font-size',Math.max(minimum,originalSize*ratio*.98));
      // Inline style overrides a class-based font size too.
      text.style.fontSize=Math.max(minimum,originalSize*ratio*.98)+'px';
      if(text.getComputedTextLength()<=limit) continue;
      let bottom=box.y+box.h-8;
      for(const other of all) {
        if(other===text)continue;
        const oy=number(other,'y'), ox=number(other,'x');
        if(oy>y+2&&ox>=box.x&&ox<=box.x+box.w) bottom=Math.min(bottom,other.getBBox().y-3);
      }
      const lines=[], words=original.trim().split(/\s+/);let line='';
      for(const word of words) {
        text.textContent=line?line+' '+word:word;
        if(line&&text.getComputedTextLength()>limit){lines.push(line);line=word;}else{line=text.textContent;}
      }
      if(line)lines.push(line);
      text.textContent='';
      lines.forEach((line,index)=>{const span=document.createElementNS('http://www.w3.org/2000/svg','tspan');span.setAttribute('x',x);span.setAttribute('y',y+index*minimum*1.2);span.textContent=line;text.appendChild(span);});
      const result=text.getBBox();
      if(result.y+result.height>bottom||result.x<box.x+3||result.x+result.width>box.x+box.w-3) {
        failures.push({asset:section.dataset.name,text:original,width:Math.round(limit),font:originalSize});
        text.textContent=original;text.setAttribute('font-size',originalSize);text.style.fontSize=originalSize+'px';
        text.setAttribute('data-fit-error','true');
      }
    }
  }
  document.querySelector('#report').textContent=JSON.stringify({assets:sections.length,failures},null,2);
  const bundle={};
  for(const section of sections){
    if(section.querySelector('[data-fit-error]'))continue;
    const svg=section.querySelector('svg');
    bundle[section.dataset.name]={source_sha256:section.dataset.source,label_sha256:section.dataset.labels,svg:new XMLSerializer().serializeToString(svg)};
  }
  const link=document.querySelector('#download');
  link.href=URL.createObjectURL(new Blob([JSON.stringify(bundle,null,2)],{type:'application/json'}));
  link.hidden=false;link.textContent='Download '+Object.keys(bundle).length+' fitted SVGs';
}
document.querySelector('#fit').addEventListener('click',fit);
'''
output = ROOT / 'site/translation-visual-preview'
output.mkdir(parents=True, exist_ok=True)
document = '<!doctype html><html lang="en"><meta charset="utf-8"><title>English SVG typography review</title><style>body{font-family:Arial;background:#e5e7eb;margin:0}header{padding:14px 24px;background:white;position:sticky;top:0;z-index:10;border-bottom:1px solid #ccc}button,a{padding:8px 14px;margin-right:18px}section{margin:25px auto;width:1200px;background:white}h2{font-size:16px;padding:12px}svg{max-width:100%;height:auto;display:block}pre{max-height:220px;overflow:auto;font-size:12px}[data-fit-error]{fill:#e11d48!important}</style><header><button id="fit">Fit English labels</button><a id="download" download="english-svg-layouts.json" hidden>Download</a><details><summary>Measurement report</summary><pre id="report">Not measured</pre></details></header>'+''.join(cards)+'<script>'+script+'</script></html>'
(output / 'index.html').write_text(document)
print(f'Prepared {len(cards)} editable figures at http://127.0.0.1:18888/translation-visual-preview/')
