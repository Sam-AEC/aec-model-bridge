using System;
using System.Collections.Generic;
using System.Linq;
using System.Text.Json;
using Autodesk.Revit.DB;
using Autodesk.Revit.UI;

namespace RevitBridge.Commands.Specialized.Phasing
{
    /// <summary>
    /// Phasing and design options commands for project timeline management
    /// Phase (#480, Score: 141), DesignOption (#481, Score: 141)
    /// </summary>
    public static class PhasingCommands
    {
        #region 1. Create Phase

        public static object CreatePhase(UIApplication app, JsonElement payload)
        {
            var doc = app.ActiveUIDocument.Document;
            string phaseName = payload.GetProperty("phase_name").GetString();
            int? afterPhaseId = payload.TryGetProperty("after_phase_id", out var ap) ? ap.GetInt32() : null;

            using (var trans = new Transaction(doc, "Create Phase"))
            {
                trans.Start();

                try
                {
                    PhaseArray phases = doc.Phases;
                    Phase newPhase = null;

                    if (afterPhaseId.HasValue)
                    {
                        Phase afterPhase = doc.GetElement(new ElementId(afterPhaseId.Value)) as Phase;
                        if (afterPhase != null)
                        {
                            // Insert phase after specified phase
                            int index = -1;
                            for (int i = 0; i < phases.Size; i++)
                            {
                                if (phases.get_Item(i).Id.IntegerValue == afterPhaseId.Value)
                                {
                                    index = i + 1;
                                    break;
                                }
                            }

                            if (index >= 0 && index <= phases.Size)
                            {
                                newPhase = phases.Insert(index);
                                newPhase.Name = phaseName;
                            }
                        }
                    }
                    else
                    {
                        // Append new phase at the end
                        newPhase = phases.Insert(phases.Size);
                        newPhase.Name = phaseName;
                    }

                    trans.Commit();

                    if (newPhase != null)
                    {
                        return new
                        {
                            success = true,
                            phaseId = newPhase.Id.IntegerValue,
                            phaseName = newPhase.Name,
                            sequenceNumber = newPhase.SequenceNumber
                        };
                    }
                    else
                    {
                        return new { success = false, error = "Failed to create phase" };
                    }
                }
                catch (Exception ex)
                {
                    return new { success = false, error = ex.Message };
                }
            }
        }

        #endregion

        #region 2. Set Element Phase

        public static object SetElementPhase(UIApplication app, JsonElement payload)
        {
            var doc = app.ActiveUIDocument.Document;
            int elementId = payload.GetProperty("element_id").GetInt32();
            int phaseCreatedId = payload.TryGetProperty("phase_created_id", out var pc) ? pc.GetInt32() : -1;
            int phaseDemolishedId = payload.TryGetProperty("phase_demolished_id", out var pd) ? pd.GetInt32() : -1;

            Element element = doc.GetElement(new ElementId(elementId));
            if (element == null)
            {
                throw new Exception($"Element {elementId} not found");
            }

            using (var trans = new Transaction(doc, "Set Element Phase"))
            {
                trans.Start();

                try
                {
                    // Set phase created
                    if (phaseCreatedId > 0)
                    {
                        Parameter phaseCreatedParam = element.get_Parameter(BuiltInParameter.PHASE_CREATED);
                        if (phaseCreatedParam != null && !phaseCreatedParam.IsReadOnly)
                        {
                            phaseCreatedParam.Set(new ElementId(phaseCreatedId));
                        }
                    }

                    // Set phase demolished
                    if (phaseDemolishedId > 0)
                    {
                        Parameter phaseDemolishedParam = element.get_Parameter(BuiltInParameter.PHASE_DEMOLISHED);
                        if (phaseDemolishedParam != null && !phaseDemolishedParam.IsReadOnly)
                        {
                            phaseDemolishedParam.Set(new ElementId(phaseDemolishedId));
                        }
                    }

                    trans.Commit();

                    return new
                    {
                        success = true,
                        elementId = elementId,
                        phaseCreatedId = phaseCreatedId,
                        phaseDemolishedId = phaseDemolishedId
                    };
                }
                catch (Exception ex)
                {
                    return new { success = false, error = ex.Message };
                }
            }
        }

        #endregion

        #region 3. Get Element Phase Info

        public static object GetElementPhaseInfo(UIApplication app, JsonElement payload)
        {
            var doc = app.ActiveUIDocument.Document;
            int elementId = payload.GetProperty("element_id").GetInt32();

            Element element = doc.GetElement(new ElementId(elementId));
            if (element == null)
            {
                throw new Exception($"Element {elementId} not found");
            }

            try
            {
                Parameter phaseCreatedParam = element.get_Parameter(BuiltInParameter.PHASE_CREATED);
                Parameter phaseDemolishedParam = element.get_Parameter(BuiltInParameter.PHASE_DEMOLISHED);

                ElementId phaseCreatedId = phaseCreatedParam?.AsElementId();
                ElementId phaseDemolishedId = phaseDemolishedParam?.AsElementId();

                Phase phaseCreated = phaseCreatedId != null && phaseCreatedId != ElementId.InvalidElementId
                    ? doc.GetElement(phaseCreatedId) as Phase
                    : null;

                Phase phaseDemolished = phaseDemolishedId != null && phaseDemolishedId != ElementId.InvalidElementId
                    ? doc.GetElement(phaseDemolishedId) as Phase
                    : null;

                return new
                {
                    success = true,
                    elementId = elementId,
                    phaseCreatedId = phaseCreated?.Id.IntegerValue,
                    phaseCreatedName = phaseCreated?.Name,
                    phaseDemolishedId = phaseDemolished?.Id.IntegerValue,
                    phaseDemolishedName = phaseDemolished?.Name
                };
            }
            catch (Exception ex)
            {
                return new { success = false, error = ex.Message };
            }
        }

        #endregion

        #region 4. Create Design Option Set

        public static object CreateDesignOptionSet(UIApplication app, JsonElement payload)
        {
            var doc = app.ActiveUIDocument.Document;
            string optionSetName = payload.GetProperty("option_set_name").GetString();

            using (var trans = new Transaction(doc, "Create Design Option Set"))
            {
                trans.Start();

                try
                {
                    DesignOptionSet optionSet = DesignOptionSet.Create(doc, optionSetName);

                    trans.Commit();

                    return new
                    {
                        success = true,
                        optionSetId = optionSet.Id.IntegerValue,
                        optionSetName = optionSet.Name,
                        defaultOptionId = optionSet.get_Parameter(BuiltInParameter.OPTION_SET_DEFAULT_OPTION)?.AsElementId().IntegerValue
                    };
                }
                catch (Exception ex)
                {
                    return new { success = false, error = ex.Message };
                }
            }
        }

        #endregion

        #region 5. Create Design Option

        public static object CreateDesignOption(UIApplication app, JsonElement payload)
        {
            var doc = app.ActiveUIDocument.Document;
            int optionSetId = payload.GetProperty("option_set_id").GetInt32();
            string optionName = payload.GetProperty("option_name").GetString();

            using (var trans = new Transaction(doc, "Create Design Option"))
            {
                trans.Start();

                try
                {
                    DesignOptionSet optionSet = doc.GetElement(new ElementId(optionSetId)) as DesignOptionSet;
                    if (optionSet == null)
                    {
                        throw new Exception($"Design option set {optionSetId} not found");
                    }

                    DesignOption option = DesignOption.Create(doc, optionSet.Id);
                    option.Name = optionName;

                    trans.Commit();

                    return new
                    {
                        success = true,
                        optionId = option.Id.IntegerValue,
                        optionName = option.Name,
                        optionSetId = optionSetId,
                        isPrimary = option.IsPrimary
                    };
                }
                catch (Exception ex)
                {
                    return new { success = false, error = ex.Message };
                }
            }
        }

        #endregion

        #region 6. Set Element Design Option

        public static object SetElementDesignOption(UIApplication app, JsonElement payload)
        {
            var doc = app.ActiveUIDocument.Document;
            int elementId = payload.GetProperty("element_id").GetInt32();
            int designOptionId = payload.GetProperty("design_option_id").GetInt32();

            Element element = doc.GetElement(new ElementId(elementId));
            if (element == null)
            {
                throw new Exception($"Element {elementId} not found");
            }

            using (var trans = new Transaction(doc, "Set Element Design Option"))
            {
                trans.Start();

                try
                {
                    DesignOption designOption = doc.GetElement(new ElementId(designOptionId)) as DesignOption;
                    if (designOption == null)
                    {
                        throw new Exception($"Design option {designOptionId} not found");
                    }

                    // Set element's design option
                    Parameter designOptionParam = element.get_Parameter(BuiltInParameter.DESIGN_OPTION_ID);
                    if (designOptionParam != null && !designOptionParam.IsReadOnly)
                    {
                        designOptionParam.Set(new ElementId(designOptionId));
                    }

                    trans.Commit();

                    return new
                    {
                        success = true,
                        elementId = elementId,
                        designOptionId = designOptionId,
                        designOptionName = designOption.Name
                    };
                }
                catch (Exception ex)
                {
                    return new { success = false, error = ex.Message };
                }
            }
        }

        #endregion

        #region 7. Get Design Option Info

        public static object GetDesignOptionInfo(UIApplication app, JsonElement payload)
        {
            var doc = app.ActiveUIDocument.Document;
            int designOptionId = payload.GetProperty("design_option_id").GetInt32();

            DesignOption designOption = doc.GetElement(new ElementId(designOptionId)) as DesignOption;
            if (designOption == null)
            {
                throw new Exception($"Design option {designOptionId} not found");
            }

            try
            {
                // Get option set
                Parameter optionSetParam = designOption.get_Parameter(BuiltInParameter.OPTION_SET_ID);
                ElementId optionSetId = optionSetParam?.AsElementId();
                DesignOptionSet optionSet = optionSetId != null && optionSetId != ElementId.InvalidElementId
                    ? doc.GetElement(optionSetId) as DesignOptionSet
                    : null;

                // Get elements in this design option
                FilteredElementCollector collector = new FilteredElementCollector(doc);
                ICollection<ElementId> elements = collector
                    .WhereElementIsNotElementType()
                    .Where(e => e.DesignOption?.Id.IntegerValue == designOptionId)
                    .ToElementIds();

                return new
                {
                    success = true,
                    optionId = designOptionId,
                    optionName = designOption.Name,
                    isPrimary = designOption.IsPrimary,
                    optionSetId = optionSet?.Id.IntegerValue,
                    optionSetName = optionSet?.Name,
                    elementCount = elements.Count
                };
            }
            catch (Exception ex)
            {
                return new { success = false, error = ex.Message };
            }
        }

        #endregion

        #region 8. List All Phases

        public static object ListAllPhases(UIApplication app, JsonElement payload)
        {
            var doc = app.ActiveUIDocument.Document;

            try
            {
                PhaseArray phases = doc.Phases;
                var phaseList = new List<object>();

                for (int i = 0; i < phases.Size; i++)
                {
                    Phase phase = phases.get_Item(i);
                    phaseList.Add(new
                    {
                        phaseId = phase.Id.IntegerValue,
                        phaseName = phase.Name,
                        sequenceNumber = phase.SequenceNumber
                    });
                }

                return new
                {
                    success = true,
                    phaseCount = phaseList.Count,
                    phases = phaseList
                };
            }
            catch (Exception ex)
            {
                return new { success = false, error = ex.Message };
            }
        }

        #endregion

        #region 9. List All Design Option Sets

        public static object ListAllDesignOptionSets(UIApplication app, JsonElement payload)
        {
            var doc = app.ActiveUIDocument.Document;

            try
            {
                FilteredElementCollector collector = new FilteredElementCollector(doc);
                var optionSets = collector
                    .OfClass(typeof(DesignOptionSet))
                    .Cast<DesignOptionSet>()
                    .Select(os => new
                    {
                        optionSetId = os.Id.IntegerValue,
                        optionSetName = os.Name,
                        defaultOptionId = os.get_Parameter(BuiltInParameter.OPTION_SET_DEFAULT_OPTION)?.AsElementId().IntegerValue
                    })
                    .ToList();

                return new
                {
                    success = true,
                    optionSetCount = optionSets.Count,
                    optionSets = optionSets
                };
            }
            catch (Exception ex)
            {
                return new { success = false, error = ex.Message };
            }
        }

        #endregion
    }
}
