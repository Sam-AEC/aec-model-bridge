using System;
using System.Collections.Generic;
using System.Linq;
using System.Text.Json;
using Autodesk.Revit.DB;
using Autodesk.Revit.DB.Mechanical;
using Autodesk.Revit.DB.Plumbing;
using Autodesk.Revit.DB.Electrical;
using Autodesk.Revit.UI;

namespace RevitBridge.Commands.Specialized.MEP
{
    /// <summary>
    /// MEP-specific commands for HVAC, Plumbing, and Electrical systems
    /// MechanicalSystem (#228, Score: 183), Connector (#229, Score: 183)
    /// </summary>
    public static class MEPCommands
    {
        #region 1. Create MEP System

        public static object CreateMEPSystem(UIApplication app, JsonElement payload)
        {
            var doc = app.ActiveUIDocument.Document;
            string systemType = payload.GetProperty("system_type").GetString(); // "Supply Air", "Return Air", "Exhaust Air", "Hydronic Supply", etc.
            var elementIds = payload.GetProperty("element_ids").EnumerateArray().Select(e => new ElementId(e.GetInt32())).ToList();

            using (var trans = new Transaction(doc, "Create MEP System"))
            {
                trans.Start();

                MechanicalSystem system = null;

                try
                {
                    // Get the first element to determine system type
                    Element firstElement = doc.GetElement(elementIds.First());

                    if (firstElement is FamilyInstance fi && fi.MEPModel is MechanicalEquipment)
                    {
                        // Create mechanical system
                        system = doc.Create.NewMechanicalSystem(null, elementIds, DuctSystemType.SupplyAir);
                    }

                    trans.Commit();

                    if (system != null)
                    {
                        return new
                        {
                            success = true,
                            systemId = system.Id.IntegerValue,
                            systemName = system.Name,
                            elementCount = elementIds.Count,
                            systemType = systemType
                        };
                    }
                    else
                    {
                        return new { success = false, error = "Failed to create MEP system" };
                    }
                }
                catch (Exception ex)
                {
                    return new { success = false, error = ex.Message };
                }
            }
        }

        #endregion

        #region 2. Add Elements to System

        public static object AddElementsToSystem(UIApplication app, JsonElement payload)
        {
            var doc = app.ActiveUIDocument.Document;
            int systemId = payload.GetProperty("system_id").GetInt32();
            var elementIds = payload.GetProperty("element_ids").EnumerateArray().Select(e => new ElementId(e.GetInt32())).ToList();

            MEPSystem system = doc.GetElement(new ElementId(systemId)) as MEPSystem;
            if (system == null)
            {
                throw new Exception($"MEP System {systemId} not found");
            }

            using (var trans = new Transaction(doc, "Add Elements to System"))
            {
                trans.Start();

                int addedCount = 0;
                foreach (var elemId in elementIds)
                {
                    try
                    {
                        system.Add(elemId);
                        addedCount++;
                    }
                    catch
                    {
                        // Element may not be compatible with system
                    }
                }

                trans.Commit();

                return new
                {
                    success = true,
                    systemId = systemId,
                    systemName = system.Name,
                    elementsAdded = addedCount,
                    totalElements = system.Elements.Count
                };
            }
        }

        #endregion

        #region 3. Connect MEP Elements

        public static object ConnectMEPElements(UIApplication app, JsonElement payload)
        {
            var doc = app.ActiveUIDocument.Document;
            int element1Id = payload.GetProperty("element1_id").GetInt32();
            int element2Id = payload.GetProperty("element2_id").GetInt32();
            int connector1Index = payload.TryGetProperty("connector1_index", out var c1) ? c1.GetInt32() : 0;
            int connector2Index = payload.TryGetProperty("connector2_index", out var c2) ? c2.GetInt32() : 0;

            Element element1 = doc.GetElement(new ElementId(element1Id));
            Element element2 = doc.GetElement(new ElementId(element2Id));

            using (var trans = new Transaction(doc, "Connect MEP Elements"))
            {
                trans.Start();

                try
                {
                    // Get connectors from elements
                    ConnectorSet connectors1 = GetConnectors(element1);
                    ConnectorSet connectors2 = GetConnectors(element2);

                    if (connectors1 == null || connectors2 == null)
                    {
                        throw new Exception("Elements do not have MEP connectors");
                    }

                    Connector conn1 = GetConnectorAtIndex(connectors1, connector1Index);
                    Connector conn2 = GetConnectorAtIndex(connectors2, connector2Index);

                    if (conn1 != null && conn2 != null)
                    {
                        conn1.ConnectTo(conn2);
                    }

                    trans.Commit();

                    return new
                    {
                        success = true,
                        element1Id = element1Id,
                        element2Id = element2Id,
                        connected = true
                    };
                }
                catch (Exception ex)
                {
                    return new { success = false, error = ex.Message };
                }
            }
        }

        #endregion

        #region 4. Size MEP Element

        public static object SizeMEPElement(UIApplication app, JsonElement payload)
        {
            var doc = app.ActiveUIDocument.Document;
            int elementId = payload.GetProperty("element_id").GetInt32();
            double size = payload.GetProperty("size").GetDouble(); // In internal units (feet)

            Element element = doc.GetElement(new ElementId(elementId));
            if (element == null)
            {
                throw new Exception($"Element {elementId} not found");
            }

            using (var trans = new Transaction(doc, "Size MEP Element"))
            {
                trans.Start();

                try
                {
                    // For ducts and pipes, set diameter or size
                    if (element is Duct duct)
                    {
                        Parameter diamParam = duct.get_Parameter(BuiltInParameter.RBS_CURVE_DIAMETER_PARAM);
                        if (diamParam != null && !diamParam.IsReadOnly)
                        {
                            diamParam.Set(size);
                        }
                    }
                    else if (element is Pipe pipe)
                    {
                        Parameter diamParam = pipe.get_Parameter(BuiltInParameter.RBS_PIPE_DIAMETER_PARAM);
                        if (diamParam != null && !diamParam.IsReadOnly)
                        {
                            diamParam.Set(size);
                        }
                    }

                    trans.Commit();

                    return new
                    {
                        success = true,
                        elementId = elementId,
                        newSize = size,
                        elementType = element.GetType().Name
                    };
                }
                catch (Exception ex)
                {
                    return new { success = false, error = ex.Message };
                }
            }
        }

        #endregion

        #region 5. Route MEP

        public static object RouteMEP(UIApplication app, JsonElement payload)
        {
            var doc = app.ActiveUIDocument.Document;
            int startConnectorElementId = payload.GetProperty("start_element_id").GetInt32();
            int endConnectorElementId = payload.GetProperty("end_element_id").GetInt32();
            string mepType = payload.GetProperty("mep_type").GetString(); // "duct", "pipe", "conduit", "cabletray"

            using (var trans = new Transaction(doc, "Route MEP"))
            {
                trans.Start();

                try
                {
                    Element startElement = doc.GetElement(new ElementId(startConnectorElementId));
                    Element endElement = doc.GetElement(new ElementId(endConnectorElementId));

                    // Get connectors
                    ConnectorSet startConnectors = GetConnectors(startElement);
                    ConnectorSet endConnectors = GetConnectors(endElement);

                    Connector startConn = GetConnectorAtIndex(startConnectors, 0);
                    Connector endConn = GetConnectorAtIndex(endConnectors, 0);

                    if (startConn == null || endConn == null)
                    {
                        throw new Exception("Could not find connectors for routing");
                    }

                    // Create routing path
                    XYZ startPoint = startConn.Origin;
                    XYZ endPoint = endConn.Origin;

                    // Simple routing - create MEP element between points
                    ElementId createdId = ElementId.InvalidElementId;

                    if (mepType.ToLower() == "duct")
                    {
                        // Get duct type
                        FilteredElementCollector collector = new FilteredElementCollector(doc);
                        DuctType ductType = collector.OfClass(typeof(DuctType)).FirstElement() as DuctType;

                        if (ductType != null)
                        {
                            Duct duct = Duct.Create(doc, ductType.Id, startElement.LevelId, startConn, endConn);
                            createdId = duct.Id;
                        }
                    }
                    else if (mepType.ToLower() == "pipe")
                    {
                        // Get pipe type
                        FilteredElementCollector collector = new FilteredElementCollector(doc);
                        PipeType pipeType = collector.OfClass(typeof(PipeType)).FirstElement() as PipeType;

                        if (pipeType != null)
                        {
                            Pipe pipe = Pipe.Create(doc, pipeType.Id, startElement.LevelId, startConn, endConn);
                            createdId = pipe.Id;
                        }
                    }

                    trans.Commit();

                    return new
                    {
                        success = true,
                        createdElementId = createdId.IntegerValue,
                        mepType = mepType,
                        startElementId = startConnectorElementId,
                        endElementId = endConnectorElementId
                    };
                }
                catch (Exception ex)
                {
                    return new { success = false, error = ex.Message };
                }
            }
        }

        #endregion

        #region 6. Create Space

        public static object CreateSpace(UIApplication app, JsonElement payload)
        {
            var doc = app.ActiveUIDocument.Document;
            int levelId = payload.GetProperty("level_id").GetInt32();
            var locationPoint = payload.GetProperty("location");

            XYZ location = new XYZ(
                locationPoint.GetProperty("x").GetDouble(),
                locationPoint.GetProperty("y").GetDouble(),
                locationPoint.GetProperty("z").GetDouble()
            );

            using (var trans = new Transaction(doc, "Create Space"))
            {
                trans.Start();

                Level level = doc.GetElement(new ElementId(levelId)) as Level;
                if (level == null)
                {
                    throw new Exception($"Level {levelId} not found");
                }

                // Create space at location
                Space space = doc.Create.NewSpace(level, new UV(location.X, location.Y));

                trans.Commit();

                return new
                {
                    success = true,
                    spaceId = space.Id.IntegerValue,
                    spaceName = space.Name,
                    levelId = levelId,
                    area = space.Area,
                    volume = space.Volume
                };
            }
        }

        #endregion

        #region 7. Calculate Space Loads

        public static object CalculateSpaceLoads(UIApplication app, JsonElement payload)
        {
            var doc = app.ActiveUIDocument.Document;
            int spaceId = payload.GetProperty("space_id").GetInt32();

            Space space = doc.GetElement(new ElementId(spaceId)) as Space;
            if (space == null)
            {
                throw new Exception($"Space {spaceId} not found");
            }

            // Get load parameters
            Parameter coolingLoadParam = space.get_Parameter(BuiltInParameter.ROOM_DESIGN_COOLING_LOAD);
            Parameter heatingLoadParam = space.get_Parameter(BuiltInParameter.ROOM_DESIGN_HEATING_LOAD);
            Parameter airflowParam = space.get_Parameter(BuiltInParameter.ROOM_DESIGN_SUPPLY_AIRFLOW);

            return new
            {
                success = true,
                spaceId = spaceId,
                spaceName = space.Name,
                coolingLoad = coolingLoadParam?.AsDouble() ?? 0,
                heatingLoad = heatingLoadParam?.AsDouble() ?? 0,
                supplyAirflow = airflowParam?.AsDouble() ?? 0,
                area = space.Area,
                volume = space.Volume
            };
        }

        #endregion

        #region 8. Get MEP System Info

        public static object GetMEPSystemInfo(UIApplication app, JsonElement payload)
        {
            var doc = app.ActiveUIDocument.Document;
            int systemId = payload.GetProperty("system_id").GetInt32();

            MEPSystem system = doc.GetElement(new ElementId(systemId)) as MEPSystem;
            if (system == null)
            {
                throw new Exception($"MEP System {systemId} not found");
            }

            var elements = system.Elements.Cast<ElementId>().Select(id => new
            {
                elementId = id.IntegerValue,
                elementType = doc.GetElement(id)?.GetType().Name
            }).ToList();

            return new
            {
                success = true,
                systemId = systemId,
                systemName = system.Name,
                elementCount = system.Elements.Count,
                elements = elements,
                systemType = system.GetType().Name
            };
        }

        #endregion

        #region 9. Set MEP Flow

        public static object SetMEPFlow(UIApplication app, JsonElement payload)
        {
            var doc = app.ActiveUIDocument.Document;
            int elementId = payload.GetProperty("element_id").GetInt32();
            double flow = payload.GetProperty("flow").GetDouble(); // CFM for air, GPM for water

            Element element = doc.GetElement(new ElementId(elementId));
            if (element == null)
            {
                throw new Exception($"Element {elementId} not found");
            }

            using (var trans = new Transaction(doc, "Set MEP Flow"))
            {
                trans.Start();

                Parameter flowParam = null;

                if (element is Duct)
                {
                    flowParam = element.get_Parameter(BuiltInParameter.RBS_DUCT_FLOW_PARAM);
                }
                else if (element is Pipe)
                {
                    flowParam = element.get_Parameter(BuiltInParameter.RBS_PIPE_FLOW_PARAM);
                }
                else if (element is FamilyInstance fi)
                {
                    flowParam = fi.get_Parameter(BuiltInParameter.RBS_DUCT_FLOW_PARAM) ??
                                fi.get_Parameter(BuiltInParameter.RBS_PIPE_FLOW_PARAM);
                }

                if (flowParam != null && !flowParam.IsReadOnly)
                {
                    flowParam.Set(flow);
                }

                trans.Commit();

                return new
                {
                    success = true,
                    elementId = elementId,
                    flow = flow,
                    elementType = element.GetType().Name
                };
            }
        }

        #endregion

        #region 10. Get Connector Info

        public static object GetConnectorInfo(UIApplication app, JsonElement payload)
        {
            var doc = app.ActiveUIDocument.Document;
            int elementId = payload.GetProperty("element_id").GetInt32();

            Element element = doc.GetElement(new ElementId(elementId));
            if (element == null)
            {
                throw new Exception($"Element {elementId} not found");
            }

            ConnectorSet connectors = GetConnectors(element);
            if (connectors == null)
            {
                return new { success = false, error = "Element has no connectors" };
            }

            var connectorList = new List<object>();
            foreach (Connector connector in connectors)
            {
                connectorList.Add(new
                {
                    origin = new { x = connector.Origin.X, y = connector.Origin.Y, z = connector.Origin.Z },
                    shape = connector.Shape.ToString(),
                    domain = connector.Domain.ToString(),
                    isConnected = connector.IsConnected,
                    flow = connector.Flow,
                    radius = connector.Radius,
                    height = connector.Height,
                    width = connector.Width
                });
            }

            return new
            {
                success = true,
                elementId = elementId,
                connectorCount = connectorList.Count,
                connectors = connectorList
            };
        }

        #endregion

        #region Helper Methods

        private static ConnectorSet GetConnectors(Element element)
        {
            if (element is FamilyInstance fi && fi.MEPModel != null)
            {
                return fi.MEPModel.ConnectorManager?.Connectors;
            }
            else if (element is MEPCurve mepCurve)
            {
                return mepCurve.ConnectorManager?.Connectors;
            }

            return null;
        }

        private static Connector GetConnectorAtIndex(ConnectorSet connectors, int index)
        {
            int i = 0;
            foreach (Connector conn in connectors)
            {
                if (i == index)
                    return conn;
                i++;
            }
            return null;
        }

        #endregion
    }
}
