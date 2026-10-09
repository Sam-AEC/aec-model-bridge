# AEC Model Bridge - MCP server image for directories and CI (Glama, Smithery, ...).
#
# This image runs the Python MCP server in MOCK mode so a registry can start it,
# list all tools with their schemas and call the read-only ones WITHOUT Autodesk
# Revit. Mock mode returns canned responses; it does not talk to a real model.
# To drive a real Revit session, install the add-in on the Windows machine that
# runs Revit and run the server there with MCP_REVIT_MODE=bridge (see README).
#
# SPDX-License-Identifier: GPL-3.0-or-later WITH Revit-Linking-Exception
# (or a commercial license - see LICENSING.md)
FROM python:3.12-slim

LABEL org.opencontainers.image.title="AEC Model Bridge" \
      org.opencontainers.image.description="MCP server for Autodesk Revit (mock mode in this image)" \
      org.opencontainers.image.source="https://github.com/Sam-AEC/aec-model-bridge" \
      org.opencontainers.image.licenses="GPL-3.0-or-later"

ENV PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    MCP_REVIT_MODE=mock \
    MCP_REVIT_WORKSPACE_DIR=/workspace \
    MCP_REVIT_ALLOWED_DIRECTORIES=/workspace \
    MCP_REVIT_AUDIT_LOG=/workspace/aec-model-bridge-audit.jsonl

WORKDIR /app
COPY packages/mcp-server-revit/ /app/

# Editable install keeps the module manifests and recipes (non-Python files)
# next to the code, exactly as in a source checkout.
RUN pip install -e . \
    && useradd --create-home --uid 10001 mcp \
    && mkdir -p /workspace \
    && chown -R mcp:mcp /workspace

USER mcp
WORKDIR /workspace

# stdio transport: the MCP client starts this container and talks over stdin/stdout.
ENTRYPOINT ["aec-model-bridge"]
