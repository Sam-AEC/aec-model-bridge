import shutil
from pathlib import Path

worktrees_dir = Path("C:/Users/sammo/worktrees/aec")
main_dir = Path("C:/Users/sammo/OneDrive/Documenten/GitHub/Autodesk-Revit-MCP-Server")

# 1. Copy Task A1 files
shutil.copy2(
    worktrees_dir / "task-a1/packages/mcp-server-revit/src/revit_mcp_server/providers/cloud.py",
    main_dir / "packages/mcp-server-revit/src/revit_mcp_server/providers/cloud.py"
)
shutil.copy2(
    worktrees_dir / "task-a1/packages/mcp-server-revit/tests/test_cloud_providers.py",
    main_dir / "packages/mcp-server-revit/tests/test_cloud_providers.py"
)
shutil.copy2(
    worktrees_dir / "task-a1/AGENT-TASK.md",
    main_dir / "AGENT-TASK-A1.md"
)

# 2. Copy Task A3 files
shutil.copy2(
    worktrees_dir / "task-a3/packages/mcp-server-revit/src/revit_mcp_server/providers/proxy.py",
    main_dir / "packages/mcp-server-revit/src/revit_mcp_server/providers/proxy.py"
)
shutil.copy2(
    worktrees_dir / "task-a3/packages/mcp-server-revit/src/revit_mcp_server/providers/__init__.py",
    main_dir / "packages/mcp-server-revit/src/revit_mcp_server/providers/__init__.py"
)
shutil.copy2(
    worktrees_dir / "task-a3/packages/mcp-server-revit/tests/test_proxy.py",
    main_dir / "packages/mcp-server-revit/tests/test_proxy.py"
)
shutil.copy2(
    worktrees_dir / "task-a3/AGENT-TASK.md",
    main_dir / "AGENT-TASK-A3.md"
)

# 3. Copy other AGENT-TASK.md files
shutil.copy2(
    worktrees_dir / "task-a5/AGENT-TASK.md",
    main_dir / "AGENT-TASK-A5.md"
)
shutil.copy2(
    worktrees_dir / "task-a8/AGENT-TASK.md",
    main_dir / "AGENT-TASK-A8.md"
)

print("Copy completed successfully!")
