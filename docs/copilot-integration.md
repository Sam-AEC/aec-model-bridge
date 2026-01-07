# Microsoft Copilot Studio Integration Guide

Complete guide to integrating RevitMCP with Microsoft Copilot Studio for conversational Revit control.

---

## Architecture Overview

Since Revit is a desktop application, direct cloud-to-desktop communication isn't possible. We use an **on-premises worker** model:

```
┌─────────────────────────────────────────────────────────┐
│ MICROSOFT CLOUD                                         │
│                                                          │
│  [User in Teams] → [Copilot Studio Agent]              │
│                            ↓                             │
│                    [MCP Server (Azure)]                  │
│                            ↓                             │
│                    [Azure Storage Queue]                 │
│                      - revit-jobs                        │
│                      - revit-results                     │
└────────────────────────────┬────────────────────────────┘
                             │
              VPN / ExpressRoute / Site-to-Site
                             │
┌────────────────────────────▼────────────────────────────┐
│ CORPORATE NETWORK                                        │
│                                                          │
│           [On-prem Revit Worker VM]                     │
│                     ↓                                    │
│           [Polls Azure Queue]                            │
│                     ↓                                    │
│           [Revit 2024 + RevitMCP Bridge]                │
│           localhost:3000                                 │
└──────────────────────────────────────────────────────────┘
```

**Why this works:**
- ✅ No inbound connections to user machines
- ✅ Worker polls Azure queue (outbound HTTPS only)
- ✅ Bridge stays localhost-only (secure by default)
- ✅ Scales with multiple workers

---

## Prerequisites

### Azure Resources
- Azure subscription with Contributor access
- Resource group for RevitMCP resources
- Microsoft Entra ID (formerly Azure AD) tenant

### On-Premises
- Windows VM or physical machine with:
  - Windows Server 2019+ or Windows 10/11 Pro
  - Revit 2024 or 2025 licensed
  - Network connectivity to Azure (ExpressRoute/VPN)
  - RevitMCP installed

### Microsoft 365
- Microsoft 365 E3/E5 license (for Teams)
- Copilot Studio license
- Admin access to Copilot Studio portal

---

## Step 1: Deploy MCP Server to Azure

### 1.1 Create Azure Container App

```bash
# Login to Azure
az login
az account set --subscription "Your-Subscription-Name"

# Create resource group
az group create \
  --name RevitMCP \
  --location eastus

# Create Container Apps environment
az containerapp env create \
  --name revit-mcp-env \
  --resource-group RevitMCP \
  --location eastus

# Deploy MCP server container
az containerapp create \
  --name revit-mcp-server \
  --resource-group RevitMCP \
  --environment revit-mcp-env \
  --image ghcr.io/sam-aec/revit-mcp-server:latest \
  --target-port 8000 \
  --ingress external \
  --min-replicas 1 \
  --max-replicas 3 \
  --cpu 0.5 \
  --memory 1.0Gi
```

**Note:** You'll need to build and push the Docker image first, or use the Python wheel.

### 1.2 Create Azure Storage Queues

```bash
# Create storage account
az storage account create \
  --name revitmcpstorage \
  --resource-group RevitMCP \
  --location eastus \
  --sku Standard_LRS

# Get connection string
CONNECTION_STRING=$(az storage account show-connection-string \
  --name revitmcpstorage \
  --resource-group RevitMCP \
  --output tsv)

# Create job queues
az storage queue create \
  --name revit-jobs \
  --connection-string "$CONNECTION_STRING"

az storage queue create \
  --name revit-results \
  --connection-string "$CONNECTION_STRING"

# Store connection string as secret
az containerapp secret set \
  --name revit-mcp-server \
  --resource-group RevitMCP \
  --secrets storage-connection="$CONNECTION_STRING"
```

### 1.3 Configure Environment Variables

```bash
az containerapp update \
  --name revit-mcp-server \
  --resource-group RevitMCP \
  --set-env-vars \
    REVIT_MCP_MODE=queue \
    AZURE_STORAGE_CONNECTION_STRING=secretref:storage-connection \
    ENABLE_AUTH=true
```

---

## Step 2: Configure Microsoft Entra ID

### 2.1 Create App Registration

```bash
# Create app registration
az ad app create \
  --display-name "RevitMCP API" \
  --sign-in-audience AzureADMyOrg \
  --web-redirect-uris "https://revit-mcp-server.azurecontainerapps.io/auth/callback"

# Get app ID
APP_ID=$(az ad app list --display-name "RevitMCP API" --query "[0].appId" -o tsv)
echo "App ID: $APP_ID"

# Create service principal
az ad sp create --id $APP_ID
```

### 2.2 Expose API Scope

1. Go to Azure Portal → Entra ID → App Registrations → RevitMCP API
2. Click **Expose an API**
3. Add Application ID URI: `api://{APP_ID}`
4. Add scope:
   - **Scope name**: `RevitMCP.Execute`
   - **Admin consent display name**: Execute Revit Tools
   - **Admin consent description**: Allows execution of Revit MCP tools
   - **State**: Enabled

### 2.3 Create Client Secret

```bash
# Create secret (save the output!)
az ad app credential reset --id $APP_ID --append

# Output will show:
# {
#   "appId": "...",
#   "password": "YOUR-SECRET-HERE",
#   "tenant": "..."
# }
```

**⚠️ Save the password immediately - you cannot retrieve it later!**

### 2.4 Update Container App with Auth

```bash
az containerapp update \
  --name revit-mcp-server \
  --resource-group RevitMCP \
  --set-env-vars \
    AZURE_TENANT_ID=<your-tenant-id> \
    AZURE_CLIENT_ID=$APP_ID \
    ALLOWED_TENANTS=<your-tenant-id>
```

---

## Step 3: Deploy On-Premises Worker

### 3.1 Provision Worker Machine

**Recommended Specs:**
- **OS**: Windows Server 2022 or Windows 11 Pro
- **CPU**: 4 cores
- **RAM**: 16 GB
- **Disk**: 100 GB SSD
- **Network**: Stable connection to Azure (ExpressRoute/VPN recommended)

**Install Prerequisites:**
1. Revit 2024/2025 (licensed)
2. RevitMCP (via `install.ps1`)
3. PowerShell 7+
4. Azure PowerShell module

```powershell
# Install Azure PowerShell
Install-Module -Name Az -AllowClobber -Scope CurrentUser
```

### 3.2 Create Worker Script

Save as `C:\RevitMCP\worker\worker.ps1`:

```powershell
param(
    [string]$StorageConnectionString = $env:AZURE_STORAGE_CONNECTION_STRING,
    [string]$BridgeUrl = "http://localhost:3000",
    [int]$PollIntervalSeconds = 5
)

$ErrorActionPreference = "Stop"

Import-Module Az.Storage

Write-Host "RevitMCP Worker starting..." -ForegroundColor Green
Write-Host "Bridge URL: $BridgeUrl" -ForegroundColor Cyan
Write-Host "Poll interval: $PollIntervalSeconds seconds" -ForegroundColor Cyan

$context = New-AzStorageContext -ConnectionString $StorageConnectionString

while ($true) {
    try {
        # Poll for jobs
        $message = Get-AzStorageQueueMessage `
            -QueueName "revit-jobs" `
            -Context $context `
            -Count 1

        if ($message) {
            $jobData = $message.MessageText | ConvertFrom-Json
            $requestId = $jobData.request_id
            $tool = $jobData.tool

            Write-Host "`n[$(Get-Date -Format 'HH:mm:ss')] Processing: $tool [$requestId]" -ForegroundColor Yellow

            # Call local bridge
            $response = Invoke-RestMethod `
                -Uri "$BridgeUrl/execute" `
                -Method POST `
                -Body ($jobData | ConvertTo-Json -Depth 10) `
                -ContentType "application/json" `
                -TimeoutSec 60

            Write-Host "  Status: $($response.status)" -ForegroundColor $(if ($response.status -eq 'ok') {'Green'} else {'Red'})

            # Push result
            $result = @{
                request_id = $requestId
                status = $response.status
                result = $response.result
                message = $response.message
                timestamp = (Get-Date).ToUniversalTime().ToString("o")
            } | ConvertTo-Json -Depth 10

            $null = New-AzStorageQueueMessage `
                -QueueName "revit-results" `
                -Content $result `
                -Context $context

            # Acknowledge (delete from queue)
            Remove-AzStorageQueueMessage `
                -QueueName "revit-jobs" `
                -Message $message `
                -Context $context

            Write-Host "  Completed [$requestId]" -ForegroundColor Green
        }

        Start-Sleep -Seconds $PollIntervalSeconds

    } catch {
        Write-Host "Error: $_" -ForegroundColor Red
        Start-Sleep -Seconds 10
    }
}
```

### 3.3 Install as Windows Service

```powershell
# Install NSSM (Non-Sucking Service Manager)
choco install nssm -y

# Create service
nssm install RevitMCPWorker `
  "C:\Program Files\PowerShell\7\pwsh.exe" `
  "-ExecutionPolicy Bypass -File C:\RevitMCP\worker\worker.ps1"

# Set environment variable with storage connection string
nssm set RevitMCPWorker AppEnvironmentExtra `
  "AZURE_STORAGE_CONNECTION_STRING=<your-connection-string>"

# Configure service
nssm set RevitMCPWorker Start SERVICE_AUTO_START
nssm set RevitMCPWorker AppStdout "C:\RevitMCP\Logs\worker-stdout.log"
nssm set RevitMCPWorker AppStderr "C:\RevitMCP\Logs\worker-stderr.log"

# Start service
nssm start RevitMCPWorker
```

### 3.4 Start Revit

**Important:** Revit must be running for the worker to execute commands.

Option 1: Manual (for testing):
- Launch Revit normally
- Open a sample project
- Leave Revit running

Option 2: Automated (for production):
- Use Revit Server or headless automation
- Consider using a dedicated automation account

### 3.5 Verify Worker

```powershell
# Check service status
nssm status RevitMCPWorker

# Check bridge health
curl http://localhost:3000/health

# Test by manually adding a job
az storage message put `
  --queue-name revit-jobs `
  --content '{"tool":"revit.health","payload":{},"request_id":"test-123"}' `
  --connection-string "<connection-string>"

# Check worker logs
Get-Content C:\RevitMCP\Logs\worker-stdout.log -Tail 20
```

---

## Step 4: Configure Copilot Studio

### 4.1 Create Agent

1. Go to [Copilot Studio](https://copilotstudio.microsoft.com)
2. Click **Create** → **New agent**
3. **Name**: "Revit Assistant"
4. **Description**: "AI assistant for Autodesk Revit automation and analysis"
5. **Instructions** (paste):

```
You are a helpful AI assistant that helps users interact with Autodesk Revit.

Available capabilities:
- Check Revit session health
- List views in active documents
- Export schedules to CSV
- Generate PDF reports
- Analyze model data

Guidelines:
- Always confirm destructive operations before executing
- Provide clear explanations of what each tool does
- If a user asks about Revit data, use the available tools
- Format results in a user-friendly way
```

### 4.2 Add MCP Server as Tool

1. In agent settings, go to **Tools** → **Add tool** → **MCP Server**
2. Fill in:
   - **Name**: RevitMCP
   - **Server URL**: `https://revit-mcp-server.azurecontainerapps.io`
   - **Authentication**: OAuth 2.0
   - **Token endpoint**: `https://login.microsoftonline.com/<tenant-id>/oauth2/v2.0/token`
   - **Client ID**: `<from Entra ID app>`
   - **Client secret**: `<from step 2.3>`
   - **Scope**: `api://<client-id>/RevitMCP.Execute`

3. Click **Validate connection** - should show green ✓

### 4.3 Select Tools

From the discovered tool catalog, enable:

**Read-only (safe for v1):**
- ✅ `revit.health` - "Check Revit session status"
- ✅ `revit.list_views` - "List all views in active document"
- ✅ `revit.export_schedules` - "Export schedule data to CSV"

**With confirmation (v2):**
- ⚠️ `revit.open_document` - Add confirmation: "Open Revit file at {path}?"
- ⚠️ `revit.export_pdf_by_sheet_set` - Add confirmation: "Export PDF to {output_path}?"

### 4.4 Test in Simulator

In the Copilot Studio test pane, try:

**Test 1: Health check**
```
User: Is Revit running?
Expected: Agent calls revit.health, responds with status
```

**Test 2: List views**
```
User: Show me all floor plan views
Expected: Agent calls revit.list_views, filters by type, displays list
```

**Test 3: Export**
```
User: Export all schedules to C:\Temp
Expected: Agent calls revit.export_schedules, confirms completion
```

### 4.5 Publish Agent

1. Click **Publish**
2. Select channels:
   - ✅ Microsoft Teams
   - ✅ Web chat (optional)
3. Assign to users:
   - Add security group: "AEC-Revit-Users"
   - Or: Publish to entire organization
4. Click **Publish** - takes ~10 minutes to propagate

---

## Step 5: Use in Microsoft Teams

### 5.1 Add to Teams

1. Open Microsoft Teams
2. Click **Apps** in left sidebar
3. Search for "Revit Assistant"
4. Click **Add**

### 5.2 Example Conversations

**Example 1: Check status**
```
User: Is Revit ready?
Revit Assistant: Yes! Revit 2024 is running with the project "Office Building.rvt" open.
```

**Example 2: List data**
```
User: What views do we have?
Revit Assistant: I found 47 views in the active document:
- Floor Plans: Level 1, Level 2, Level 3, Site Plan
- 3D Views: Default 3D, Rendering View
- Ceiling Plans: Level 1 RCP, Level 2 RCP
... (would you like the full list?)
```

**Example 3: Export**
```
User: Export all schedules to my desktop
Revit Assistant: I'll export the schedules to your desktop.
[Calls revit.export_schedules]
Done! Exported 8 schedules:
- Door Schedule.csv
- Room Schedule.csv
- Window Schedule.csv
...
```

---

## End-to-End Flow Diagram

```
1. User in Teams: "List all views"
         ↓
2. Copilot Studio → Parses intent → Calls MCP tool revit.list_views
         ↓
3. MCP Server (Azure) → Enqueues job to Azure Storage Queue
         {
           "tool": "revit.list_views",
           "payload": {},
           "request_id": "abc-123"
         }
         ↓
4. On-prem Worker → Polls queue (every 5s) → Gets job
         ↓
5. Worker → POST http://localhost:3000/execute
         ↓
6. Bridge → Queues in CommandQueue → Raises ExternalEvent
         ↓
7. Revit → Execute on main thread → FilteredElementCollector
         ↓
8. Bridge → Returns {"status":"ok", "result":{views:[...]}}
         ↓
9. Worker → Pushes result to revit-results queue
         ↓
10. MCP Server → Polls results → Gets response
         ↓
11. Copilot Studio → Formats response → Returns to Teams
         ↓
12. User sees: "Found 47 views: Floor Plan - Level 1, ..."
```

**Typical latency**: 3-8 seconds (polling overhead + execution time)

---

## Troubleshooting

### Issue: "Bridge unreachable"

**Symptoms**: Worker shows "Connection refused" errors

**Solutions**:
1. Check Revit is running: `Get-Process Revit`
2. Check bridge health: `curl http://localhost:3000/health`
3. Check RevitMCP add-in loaded in Revit journal:
   ```
   C:\Users\<user>\AppData\Local\Autodesk\Revit\Autodesk Revit 2024\Journals\
   ```
4. Restart Revit

### Issue: "Unauthorized" from Azure

**Symptoms**: 401 errors in Container Apps logs

**Solutions**:
1. Verify Entra ID token:
   ```bash
   az ad app show --id <app-id>
   ```
2. Check tenant ID matches in both places
3. Regenerate client secret if expired

### Issue: Jobs stuck in queue

**Symptoms**: Messages in `revit-jobs` but not processed

**Solutions**:
1. Check worker service:
   ```powershell
   nssm status RevitMCPWorker
   Get-Content C:\RevitMCP\Logs\worker-stdout.log -Tail 50
   ```
2. Check queue visibility:
   ```bash
   az storage queue peek --name revit-jobs --connection-string "..."
   ```
3. Restart worker:
   ```powershell
   nssm restart RevitMCPWorker
   ```

### Issue: Timeout errors

**Symptoms**: Requests timeout after 30s

**Solutions**:
1. Increase timeout in worker script (`-TimeoutSec 120`)
2. Increase timeout in bridge ([BridgeServer.cs:line](packages/revit-bridge-addin/src/Bridge/BridgeServer.cs))
3. For long-running exports, implement async pattern

---

## Security Considerations

### Authentication Flow
```
Teams User → Copilot → MCP Server (validates JWT) → Queue → Worker (localhost)
```

- ✅ User authenticated by Teams/M365
- ✅ Copilot → MCP authenticated by OAuth2 (Entra ID)
- ✅ Worker → Bridge local-only (no auth needed)

### Network Isolation
- MCP server in Azure (public HTTPS)
- Worker in corporate network (polls outbound only)
- Bridge localhost-only (127.0.0.1:3000)

### Data Flow
- All requests logged with user identity
- Audit logs in both Azure and on-prem
- Workspace sandboxing enforced

---

## Cost Estimate

**Azure Resources (monthly):**
- Container Apps: ~$50 (always-on, 1 replica)
- Storage Queue: ~$1
- Log Analytics: ~$10
- Bandwidth: ~$5

**Total: ~$66/month** (excludes Revit license, worker VM, network)

---

## Next Steps

1. ✅ Deploy Azure infrastructure
2. ✅ Configure Entra ID
3. ✅ Deploy on-prem worker
4. ✅ Test end-to-end in Copilot Studio
5. Scale: Add more workers for parallel execution
6. Enhance: Add more tools (PDF, IFC, audits)
7. Monitor: Set up alerting for queue depth, failures

---

**Questions?** Open an issue on [GitHub](https://github.com/Sam-AEC/Autodesk-Revit-MCP-Server/issues)
