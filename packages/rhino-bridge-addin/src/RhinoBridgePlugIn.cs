using System;
using Rhino;
using Rhino.PlugIns;

namespace RhinoBridge
{
    public class RhinoBridgePlugIn : PlugIn
    {
        private BridgeServer? _server;

        public RhinoBridgePlugIn()
        {
            Instance = this;
        }

        public static RhinoBridgePlugIn Instance { get; private set; }

        protected override LoadReturnCode OnLoad(ref string errorMessage)
        {
            try
            {
                // Start the HTTP bridge on port 3004
                _server = new BridgeServer(3004);
                _server.Start();
                RhinoApp.WriteLine($"AEC Model Bridge for Rhino started on port 3004.");
                return LoadReturnCode.Success;
            }
            catch (Exception ex)
            {
                errorMessage = ex.Message;
                return LoadReturnCode.ErrorNoDialog;
            }
        }

        protected override void OnShutdown()
        {
            if (_server != null)
            {
                _server.Stop();
                _server = null;
            }
            base.OnShutdown();
        }
    }
}
