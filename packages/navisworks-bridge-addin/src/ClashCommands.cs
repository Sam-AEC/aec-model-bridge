using System;
using System.Collections.Generic;
using System.Linq;
using System.Text.Json;
using Autodesk.Navisworks.Api;
using Autodesk.Navisworks.Api.Clash;
using Application = Autodesk.Navisworks.Api.Application;

namespace NavisworksBridge
{
    public static class ClashCommands
    {
        [BridgeCommand("navis.list_clash_tests", IsMutating = false)]
        public static object ListClashTests()
        {
            var doc = Application.ActiveDocument;
            var clashTests = doc.GetClash().TestsData.Tests;

            var list = new List<object>();
            foreach (var test in clashTests)
            {
                var ct = test as ClashTest;
                list.Add(new
                {
                    displayName = test.DisplayName,
                    guid = test.Guid.ToString(),
                    testType = ct?.TestType.ToString() ?? "Unknown",
                    status = ct?.Status.ToString() ?? "Unknown"
                });
            }

            return new { count = list.Count, tests = list };
        }

        [BridgeCommand("navis.run_clash_test", IsMutating = true)]
        public static object RunClashTest(JsonElement payload)
        {
            var doc = Application.ActiveDocument;
            var guidStr = payload.GetProperty("guid").GetString();
            if (!Guid.TryParse(guidStr, out var guid))
            {
                throw new ArgumentException("Invalid GUID");
            }

            var clashData = doc.GetClash().TestsData;
            var test = clashData.Tests.FirstOrDefault(t => t.Guid == guid) as ClashTest;
            
            if (test == null)
            {
                throw new ArgumentException("Clash test not found");
            }

            clashData.TestsRunTest(test);

            return new
            {
                status = "success",
                test = test.DisplayName,
                clashCount = test.Children.Count
            };
        }

        [BridgeCommand("navis.get_clash_results", IsMutating = false)]
        public static object GetClashResults(JsonElement payload)
        {
            var doc = Application.ActiveDocument;
            var guidStr = payload.GetProperty("guid").GetString();
            if (!Guid.TryParse(guidStr, out var guid))
            {
                throw new ArgumentException("Invalid GUID");
            }

            var clashData = doc.GetClash().TestsData;
            var test = clashData.Tests.FirstOrDefault(t => t.Guid == guid) as ClashTest;
            
            if (test == null)
            {
                throw new ArgumentException("Clash test not found");
            }

            int skip = payload.TryGetProperty("skip", out var sk) ? sk.GetInt32() : 0;
            int limit = payload.TryGetProperty("limit", out var lim) ? lim.GetInt32() : 50;

            var results = test.Children.OfType<ClashResult>().Skip(skip).Take(limit);
            var resultList = new List<object>();

            foreach (var res in results)
            {
                resultList.Add(new
                {
                    displayName = res.DisplayName,
                    guid = res.Guid.ToString(),
                    status = res.Status.ToString(),
                    distance = res.Distance,
                    center = res.Center != null ? new { x = res.Center.X, y = res.Center.Y, z = res.Center.Z } : null,
                    item1 = GetItemIdentity(res.Item1),
                    item2 = GetItemIdentity(res.Item2)
                });
            }

            return new
            {
                test = test.DisplayName,
                totalClashes = test.Children.Count,
                returned = resultList.Count,
                results = resultList
            };
        }

        private static object GetItemIdentity(ModelItem item)
        {
            if (item == null) return null;

            string ifcGuid = null;
            var ifcProps = item.PropertyCategories.FindCategoryByDisplayName("Item");
            if (ifcProps != null)
            {
                var guidProp = ifcProps.Properties.FindPropertyByDisplayName("Guid");
                if (guidProp != null)
                {
                    ifcGuid = guidProp.Value.ToDisplayString();
                }
            }

            return new
            {
                displayName = item.DisplayName,
                className = item.ClassName,
                instanceGuid = item.InstanceGuid.ToString(),
                ifcGuid = ifcGuid
            };
        }
    }
}
