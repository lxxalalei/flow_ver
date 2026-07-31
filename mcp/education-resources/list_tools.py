#!/usr/bin/env python3
"""List MCP server tools"""
import sys, asyncio
sys.stdout.reconfigure()

try:
    from education_resource_mcp.server import mcp
    # FastMCP - list tools via the protocol
    if hasattr(mcp, '_tool_manager'):
        tm = mcp._tool_manager
        if hasattr(tm, '_tools'):
            tools = tm._tools
            print(f"Tools registered: {len(tools)}")
            for name, tool in tools.items():
                desc = getattr(tool, 'description', '') or ''
                print(f"  - {name}: {desc[:100]}")
    elif hasattr(mcp, 'list_tools'):
        tools = asyncio.run(mcp.list_tools())
        print(f"Tools: {len(tools)}")
        for t in tools:
            print(f"  - {t.name}: {(t.description or '')[:100]}")
    else:
        print(f"mcp type: {type(mcp)}")
        print(f"mcp attrs: {[a for a in dir(mcp) if not a.startswith('__')]}")
except Exception as e:
    print(f"Error: {e}")
    import traceback
    traceback.print_exc()
