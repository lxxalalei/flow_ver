#!/usr/bin/env python3
import json, sys
sys.stdout.reconfigure()
with open('/mnt/c/Users/admin/AppData/Local/Temp/searx_result2.json') as f:
    d = json.load(f)
results = d.get('results', [])
print(f'results: {len(results)}')
unres = d.get('unresponsive_engines', [])
print(f'unresponsive: {[e[0] if isinstance(e, list) else e for e in unres]}')
for r in results[:10]:
    print(f'  - {r.get("title","?")[:60]}')
    print(f'    {r.get("url","")[:80]}')
