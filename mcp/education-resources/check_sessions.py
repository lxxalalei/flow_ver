#!/usr/bin/env python3
"""Check all sessions after login helper"""
import json, sys, glob
sys.stdout.reconfigure()

for f in sorted(glob.glob("/home/admin_quanxiao/.local/share/quanxiao/education-resource-mcp-data/sessions/*.json")):
    with open(f) as fh:
        d = json.load(fh)
    platform = d.get("platform")
    sd = d.get("session_data", {})
    cookies = sd.get("cookies", [])
    storage = sd.get("storage", {})
    print(f"  {platform:12s}  cookies={len(cookies):2d}  storage={len(storage):2d}  captured={d.get('captured_at','')[:19]}  expires={d.get('expires_at','')[:10]}")
