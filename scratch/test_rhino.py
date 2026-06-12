import asyncio
from revit_mcp_server.providers.rhino import RhinoProvider
from revit_mcp_server.security.workspace import WorkspaceMonitor
from revit_mcp_server.config import ServerConfig

async def test_rhino():
    config = ServerConfig()
    workspace = WorkspaceMonitor(config)
    provider = RhinoProvider(workspace)
    print('Testing Rhino Health Endpoint...')
    try:
        health = await provider.check_health()
        print(f'Rhino Compute Health: {health}')
    except Exception as e:
        print(f'Error checking health: {e}')

if __name__ == '__main__':
    asyncio.run(test_rhino())
