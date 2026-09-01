#!/usr/bin/env python3
"""List MCP server tools"""
import sys, asyncio
sys.stdout.reconfigure()

try:
    from education_resource_mcp.server import create_server

    tools = asyncio.run(create_server().list_tools())
    print(f"Tools: {len(tools)}")
    for tool in tools:
        print(f"  - {tool.name}: {(tool.description or '')[:100]}")
except Exception as e:
    print(f"Error: {e}")
    import traceback
    traceback.print_exc()
