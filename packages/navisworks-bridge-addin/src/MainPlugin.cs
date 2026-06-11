using System;
using System.Windows.Threading;
using Autodesk.Navisworks.Api.Plugins;

namespace NavisworksBridge
{
    [Plugin("AECModelBridgeNavisworks", "Sam-AEC", DisplayName = "AEC Model Bridge", ToolTip = "Bridge to MCP Server")]
    [AddInPlugin(AddInLocation.AddIn)]
    public class MainPlugin : AddInPlugin
    {
        private static BridgeServer? _server;

        public override int Execute(params string[] parameters)
        {
            if (_server == null)
            {
                try
                {
                    // Capture the main thread dispatcher
                    var dispatcher = Dispatcher.CurrentDispatcher;
                    _server = new BridgeServer(dispatcher);
                    _server.Start();
                    System.Windows.Forms.MessageBox.Show("AEC Model Bridge for Navisworks started on port 3002.");
                }
                catch (Exception ex)
                {
                    System.Windows.Forms.MessageBox.Show("Failed to start AEC Model Bridge:\n" + ex.Message + "\n\n" + ex.StackTrace);
                    _server = null;
                }
            }
            else
            {
                _server.Stop();
                _server = null;
                System.Windows.Forms.MessageBox.Show("AEC Model Bridge for Navisworks stopped.");
            }
            return 0;
        }
    }
}
