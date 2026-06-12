import asyncio
from revit_mcp_server.config import config
from revit_mcp_server.security.workspace import WorkspaceMonitor
from revit_mcp_server.providers.rhino import RhinoProvider

async def test_rhino_query():
    print('Initializing Rhino test...')
    workspace = WorkspaceMonitor(config.allowed_directories)
    provider = RhinoProvider(workspace)
    
    print('Checking Rhino Compute Health...')
    try:
        health = await provider.check_health()
        print(f'Health Response: {health}')
    except Exception as e:
        print(f'Failed Health Check: {e}')

    # Find the tool
    tools = provider.get_tools()
    query_tool = next((t for t in tools if t.name == 'rhino_query_file_geometry'), None)
    
    if not query_tool:
        print('Tool rhino_query_file_geometry not found!')
        return
        
    print('\nExecuting rhino_query_file_geometry on Untitled.3dm...')
    file_path = r'C:\Users\sammo\OneDrive\Documenten\GitHub\Autodesk-Revit-MCP-Server\docs\Untitled.3dm'
    
    params = {
        'file_path': file_path,
        'extract_breps': True,
        'extract_meshes': True
    }
    
    try:
        result = await query_tool.handler(params)
        print('\n--- Query Result ---')
        # Print a truncated preview if it's large
        res_str = str(result)
        if len(res_str) > 1000:
            print(res_str[:1000] + '... [truncated]')
        else:
            print(res_str)
    except Exception as e:
        print(f'Query Failed: {e}')

if __name__ == '__main__':
    asyncio.run(test_rhino_query())
