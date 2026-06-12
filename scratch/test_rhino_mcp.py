import asyncio
from mcp import ClientSession
from mcp.client.sse import sse_client
import httpx

async def test_rhino_mcp():
    print('Connecting to Rhino MCP at http://localhost:9876/sse...')
    url = 'http://localhost:9876/sse'
    try:
        async with sse_client(url) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()
                print('Session initialized!')
                tools = await session.list_tools()
                for tool in tools.tools:
                    print(f'Tool: {tool.name} - {tool.description}')
    except Exception as e:
        print(f'Error connecting: {e}')

if __name__ == '__main__':
    asyncio.run(test_rhino_mcp())
