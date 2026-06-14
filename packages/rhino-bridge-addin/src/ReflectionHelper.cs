using System;
using System.Collections.Generic;
using System.Linq;
using System.Reflection;
using System.Text.Json;
using Rhino;
using Rhino.DocObjects;

namespace RhinoBridge
{
    public static class ReflectionHelper
    {
        private static Dictionary<string, object> _objectRegistry = new Dictionary<string, object>();
        private static int _objectIdCounter = 0;

        public static string RegisterObject(object obj)
        {
            if (obj == null) return null;
            if (obj is RhinoObject elem) return elem.Id.ToString();

            string id = $"obj_{++_objectIdCounter}";
            _objectRegistry[id] = obj;
            return id;
        }

        public static object GetObject(string id, RhinoDoc doc)
        {
            if (string.IsNullOrEmpty(id)) return null;

            if (_objectRegistry.ContainsKey(id)) return _objectRegistry[id];

            if (Guid.TryParse(id, out Guid guid))
            {
                return doc.Objects.FindId(guid);
            }

            return null;
        }

        public static void ClearRegistry()
        {
            _objectRegistry.Clear();
            _objectIdCounter = 0;
        }

        public static object ParseArgument(JsonElement arg, RhinoDoc doc)
        {
            switch (arg.ValueKind)
            {
                case JsonValueKind.String:
                    return arg.GetString();
                case JsonValueKind.Number:
                    if (arg.TryGetInt32(out int i)) return i;
                    return arg.GetDouble();
                case JsonValueKind.True: return true;
                case JsonValueKind.False: return false;
                case JsonValueKind.Null: return null;
                case JsonValueKind.Object:
                    if (arg.TryGetProperty("type", out var typeProp) && typeProp.GetString() == "reference")
                    {
                        return GetObject(arg.GetProperty("id").GetString(), doc);
                    }
                    if (arg.TryGetProperty("x", out _) && arg.TryGetProperty("y", out _) && arg.TryGetProperty("z", out _))
                    {
                        return new Rhino.Geometry.Point3d(arg.GetProperty("x").GetDouble(), arg.GetProperty("y").GetDouble(), arg.GetProperty("z").GetDouble());
                    }
                    return null;
                default:
                    return null;
            }
        }

        public static Type ResolveType(string typeName)
        {
            if (typeName == "int" || typeName == "System.Int32") return typeof(int);
            if (typeName == "double" || typeName == "System.Double") return typeof(double);
            if (typeName == "string" || typeName == "System.String") return typeof(string);
            if (typeName == "bool" || typeName == "System.Boolean") return typeof(bool);

            var assemblies = AppDomain.CurrentDomain.GetAssemblies()
                .Where(a => a.FullName.StartsWith("RhinoCommon") || a.FullName.StartsWith("System"));
            
            foreach (var asm in assemblies)
            {
                var type = asm.GetType(typeName) ?? asm.GetType("Rhino." + typeName) ?? asm.GetType("Rhino.Geometry." + typeName) ?? asm.GetType("Rhino.DocObjects." + typeName);
                if (type != null) return type;
            }

            return null;
        }

        public static object InvokeMethod(RhinoDoc doc, string typeName, string methodName, JsonElement argsElement, string targetId = null)
        {
            Type type = ResolveType(typeName);
            if (type == null) throw new Exception($"Type '{typeName}' not found.");

            object target = null;
            if (!string.IsNullOrEmpty(targetId))
            {
                target = GetObject(targetId, doc);
                if (target == null) throw new Exception($"Target object '{targetId}' not found.");
            }

            List<object> args = new List<object>();
            if (argsElement.ValueKind == JsonValueKind.Array)
            {
                foreach (var argJson in argsElement.EnumerateArray())
                {
                    args.Add(ParseArgument(argJson, doc));
                }
            }

            if (methodName == "new" || methodName == "ctor")
            {
                var constructors = type.GetConstructors().Where(c => c.GetParameters().Length == args.Count).ToList();
                if (constructors.Count == 0) throw new Exception($"Constructor with {args.Count} arguments not found on type '{type.Name}'.");
                
                var ctor = constructors.First();
                var ctorParams = ctor.GetParameters();
                object[] ctorArgs = new object[args.Count];
                
                for (int i = 0; i < args.Count; i++)
                {
                    var targetType = ctorParams[i].ParameterType;
                    var val = args[i];
                    
                    if (targetType.IsEnum)
                    {
                        if (val is string s) val = Enum.Parse(targetType, s);
                        else if (val is int n) val = Enum.ToObject(targetType, n);
                    }
                    
                    if (val is IConvertible && !targetType.IsAssignableFrom(val.GetType()))
                    {
                       try { val = Convert.ChangeType(val, targetType); } catch {}
                    }
                    ctorArgs[i] = val;
                }

                object instance = ctor.Invoke(ctorArgs);
                string regId = RegisterObject(instance);
                return new { type = "reference", id = regId, class_name = instance.GetType().Name, str = instance.ToString() };
            }

            var flags = BindingFlags.Public | BindingFlags.Instance | BindingFlags.Static | BindingFlags.FlattenHierarchy;
            var methods = type.GetMethods(flags).Where(m => m.Name == methodName && m.GetParameters().Length == args.Count).ToList();

            if (methods.Count == 0) throw new Exception($"Method '{methodName}' with {args.Count} arguments not found on type '{type.Name}'.");
            
            MethodInfo methodToInvoke = methods.First();
            var parameters = methodToInvoke.GetParameters();
            object[] finalArgs = new object[args.Count];
            for (int i = 0; i < args.Count; i++)
            {
                var targetType = parameters[i].ParameterType;
                var val = args[i];
                
                if (targetType.IsEnum)
                {
                    if (val is string s) val = Enum.Parse(targetType, s);
                    else if (val is int n) val = Enum.ToObject(targetType, n);
                }
                
                if (val is IConvertible && !targetType.IsAssignableFrom(val.GetType()))
                {
                   try { val = Convert.ChangeType(val, targetType); } catch {}
                }

                finalArgs[i] = val;
            }

            object result = methodToInvoke.Invoke(target, finalArgs);

            if (result == null) return null;
            if (result is Guid guid) return guid.ToString();
            if (result.GetType().IsPrimitive || result is string) return result;

            string resultRegId = RegisterObject(result);
            return new { type = "reference", id = resultRegId, class_name = result.GetType().Name, str = result.ToString() };
        }
    }
}
