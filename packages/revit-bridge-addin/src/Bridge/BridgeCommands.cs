using System;
using Autodesk.Revit.Attributes;
using Autodesk.Revit.DB;
using Autodesk.Revit.UI;

namespace RevitBridge.Bridge
{
    [Transaction(TransactionMode.Manual)]
    public class CommandConnect : IExternalCommand
    {
        public Result Execute(ExternalCommandData commandData, ref string message, ElementSet elements)
        {
            if (App.Server != null)
            {
                if (!App.Server.IsListening)
                {
                    App.Server.Start();
                    TaskDialog.Show("RevitMCP", "Bridge Server Started Successfully.");
                }
                else
                {
                    TaskDialog.Show("RevitMCP", "Bridge Server is already running.");
                }
            }
            return Result.Succeeded;
        }
    }

    [Transaction(TransactionMode.Manual)]
    public class CommandDisconnect : IExternalCommand
    {
        public Result Execute(ExternalCommandData commandData, ref string message, ElementSet elements)
        {
            if (App.Server != null)
            {
                if (App.Server.IsListening)
                {
                    App.Server.Stop();
                    TaskDialog.Show("RevitMCP", "Bridge Server Stopped.");
                }
                else
                {
                    TaskDialog.Show("RevitMCP", "Bridge Server is already stopped.");
                }
            }
            return Result.Succeeded;
        }
    }

    [Transaction(TransactionMode.Manual)]
    public class CommandStatus : IExternalCommand
    {
        public Result Execute(ExternalCommandData commandData, ref string message, ElementSet elements)
        {
            string status = App.Server?.IsListening == true ? "Running ✅" : "Stopped 🛑";
            string version = App.RevitVersion ?? "Unknown";
            string port = "8000"; // Assuming default, or we can expose Port property on Server

            TaskDialog.Show("RevitMCP Status", 
                $"Status: {status}\n" +
                $"Revit Version: {version}\n" +
                $"Address: http://localhost:{port}/");
            
            return Result.Succeeded;
        }
    }
}
