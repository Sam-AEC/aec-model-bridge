using System;
using System.Collections.Generic;
using System.Linq;
using System.Text.Json;
using Autodesk.Navisworks.Api;
using Application = Autodesk.Navisworks.Api.Application;

namespace NavisworksBridge
{
    public static class BridgeCommandFactory
    {
        private static readonly Dictionary<string, Func<JsonElement, object>> _handlers = new();
        private static readonly List<object> _capabilities = new();
        private static readonly List<string> _catalog = new();

        static BridgeCommandFactory()
        {
            var types = new[] { typeof(BridgeCommandFactory), typeof(BridgeCommands), typeof(ClashCommands) };
            foreach (var type in types)
            {
                var methods = type.GetMethods(System.Reflection.BindingFlags.Public | System.Reflection.BindingFlags.NonPublic | System.Reflection.BindingFlags.Static);
                foreach (var method in methods)
                {
                    var attr = (BridgeCommandAttribute)Attribute.GetCustomAttribute(method, typeof(BridgeCommandAttribute));
                    if (attr != null)
                    {
                        var func = CreateHandlerDelegate(method);
                        _handlers[attr.Name] = func;
                        _catalog.Add(attr.Name);
                        _capabilities.Add(new
                        {
                            name = attr.Name,
                            is_mutating = attr.IsMutating,
                            confirmation_required = attr.ConfirmationRequired
                        });
                    }
                }
            }
        }

        private static Func<JsonElement, object> CreateHandlerDelegate(System.Reflection.MethodInfo method)
        {
            var parameters = method.GetParameters();
            if (parameters.Length == 0)
            {
                return (payload) => method.Invoke(null, null);
            }
            else if (parameters.Length == 1)
            {
                return (payload) => method.Invoke(null, new object[] { payload });
            }
            throw new InvalidOperationException($"Method {method.Name} has invalid parameters.");
        }

        public static object Execute(string tool, JsonElement payload)
        {
            if (_handlers.TryGetValue(tool, out var handler))
            {
                try
                {
                    return handler(payload);
                }
                catch (System.Reflection.TargetInvocationException ex)
                {
                    throw ex.InnerException ?? ex;
                }
            }
            return new { status = "error", message = $"Unknown tool: {tool}" };
        }

        public static List<string> GetToolCatalog() => _catalog;

        public static object GetCapabilities() => _capabilities;

        [BridgeCommand("navisworks.health", IsMutating = false)]
        private static object ExecuteHealth()
        {
            var doc = Application.ActiveDocument;
            return new
            {
                status = "healthy",
                application = "navisworks",
                title = doc.Title ?? "",
                fileName = doc.FileName ?? "",
                modelsCount = doc.Models.Count
            };
        }

        [BridgeCommand("navis.echo", IsMutating = false)]
        private static object ExecuteEcho(JsonElement payload)
        {
            var message = payload.TryGetProperty("message", out var m) ? m.GetString() ?? "" : "";
            return new { echo = message, application = "navisworks" };
        }
    }
}
