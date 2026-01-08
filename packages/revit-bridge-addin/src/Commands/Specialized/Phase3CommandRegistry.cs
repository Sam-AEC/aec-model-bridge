using System;
using System.Text.Json;
using Autodesk.Revit.UI;
using RevitBridge.Commands.Specialized.MEP;
using RevitBridge.Commands.Specialized.Structural;
using RevitBridge.Commands.Specialized.Stairs;
using RevitBridge.Commands.Specialized.Phasing;

namespace RevitBridge.Commands.Specialized
{
    /// <summary>
    /// Registry for Phase 3 commands (28 specialized tools)
    /// These are discipline-specific tools for advanced professional workflows
    /// </summary>
    public static class Phase3CommandRegistry
    {
        public static object Execute(UIApplication app, string tool, JsonElement payload)
        {
            return tool switch
            {
                // === MEP COMMANDS (10 tools) - HVAC, Plumbing, Electrical ===
                // MechanicalSystem (#228, Score: 183), Connector (#229, Score: 183)

                "revit.create_mep_system" => MEPCommands.CreateMEPSystem(app, payload),
                "revit.add_elements_to_system" => MEPCommands.AddElementsToSystem(app, payload),
                "revit.connect_mep_elements" => MEPCommands.ConnectMEPElements(app, payload),
                "revit.size_mep_element" => MEPCommands.SizeMEPElement(app, payload),
                "revit.route_mep" => MEPCommands.RouteMEP(app, payload),
                "revit.create_space" => MEPCommands.CreateSpace(app, payload),
                "revit.calculate_space_loads" => MEPCommands.CalculateSpaceLoads(app, payload),
                "revit.get_mep_system_info" => MEPCommands.GetMEPSystemInfo(app, payload),
                "revit.set_mep_flow" => MEPCommands.SetMEPFlow(app, payload),
                "revit.get_connector_info" => MEPCommands.GetConnectorInfo(app, payload),

                // === STRUCTURAL COMMANDS (8 tools) - Framing, Loads, Analysis ===
                // StructuralType (#344, Score: 159), AnalyticalModel (#372, Score: 155)

                "revit.create_structural_framing" => StructuralCommands.CreateStructuralFraming(app, payload),
                "revit.create_structural_column" => StructuralCommands.CreateStructuralColumn(app, payload),
                "revit.create_truss" => StructuralCommands.CreateTruss(app, payload),
                "revit.place_rebar" => StructuralCommands.PlaceRebar(app, payload),
                "revit.create_load_case" => StructuralCommands.CreateLoadCase(app, payload),
                "revit.apply_point_load" => StructuralCommands.ApplyPointLoad(app, payload),
                "revit.apply_line_load" => StructuralCommands.ApplyLineLoad(app, payload),
                "revit.get_analytical_model" => StructuralCommands.GetAnalyticalModel(app, payload),

                // === STAIRS & RAILINGS COMMANDS (6 tools) - Circulation Design ===
                // Stairs (#539, Score: 133), StairsRun (#540, Score: 133), Railing (#541, Score: 133)

                "revit.create_stairs_by_sketch" => StairsCommands.CreateStairsBySketch(app, payload),
                "revit.create_railing" => StairsCommands.CreateRailing(app, payload),
                "revit.set_stairs_path" => StairsCommands.SetStairsPath(app, payload),
                "revit.modify_stairs_run" => StairsCommands.ModifyStairsRun(app, payload),
                "revit.get_stairs_info" => StairsCommands.GetStairsInfo(app, payload),
                "revit.get_railing_info" => StairsCommands.GetRailingInfo(app, payload),

                // === PHASING & DESIGN OPTIONS COMMANDS (9 tools) - Project Timeline ===
                // Phase (#480, Score: 141), DesignOption (#481, Score: 141)

                "revit.create_phase" => PhasingCommands.CreatePhase(app, payload),
                "revit.set_element_phase" => PhasingCommands.SetElementPhase(app, payload),
                "revit.get_element_phase_info" => PhasingCommands.GetElementPhaseInfo(app, payload),
                "revit.create_design_option_set" => PhasingCommands.CreateDesignOptionSet(app, payload),
                "revit.create_design_option" => PhasingCommands.CreateDesignOption(app, payload),
                "revit.set_element_design_option" => PhasingCommands.SetElementDesignOption(app, payload),
                "revit.get_design_option_info" => PhasingCommands.GetDesignOptionInfo(app, payload),
                "revit.list_all_phases" => PhasingCommands.ListAllPhases(app, payload),
                "revit.list_all_design_option_sets" => PhasingCommands.ListAllDesignOptionSets(app, payload),

                _ => null // Return null to let main factory handle unknown commands
            };
        }

        /// <summary>
        /// Get list of all Phase 3 command names for documentation/validation
        /// </summary>
        public static string[] GetCommandNames()
        {
            return new[]
            {
                // MEP (10)
                "revit.create_mep_system",
                "revit.add_elements_to_system",
                "revit.connect_mep_elements",
                "revit.size_mep_element",
                "revit.route_mep",
                "revit.create_space",
                "revit.calculate_space_loads",
                "revit.get_mep_system_info",
                "revit.set_mep_flow",
                "revit.get_connector_info",

                // Structural (8)
                "revit.create_structural_framing",
                "revit.create_structural_column",
                "revit.create_truss",
                "revit.place_rebar",
                "revit.create_load_case",
                "revit.apply_point_load",
                "revit.apply_line_load",
                "revit.get_analytical_model",

                // Stairs & Railings (6)
                "revit.create_stairs_by_sketch",
                "revit.create_railing",
                "revit.set_stairs_path",
                "revit.modify_stairs_run",
                "revit.get_stairs_info",
                "revit.get_railing_info",

                // Phasing & Design Options (9)
                "revit.create_phase",
                "revit.set_element_phase",
                "revit.get_element_phase_info",
                "revit.create_design_option_set",
                "revit.create_design_option",
                "revit.set_element_design_option",
                "revit.get_design_option_info",
                "revit.list_all_phases",
                "revit.list_all_design_option_sets"
            };
        }
    }
}
