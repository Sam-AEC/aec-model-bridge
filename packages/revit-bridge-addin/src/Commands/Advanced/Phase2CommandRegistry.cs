using System;
using System.Text.Json;
using Autodesk.Revit.UI;
using RevitBridge.Commands.Advanced.Geometry;
using RevitBridge.Commands.Advanced.Families;
using RevitBridge.Commands.Advanced.Worksharing;
using RevitBridge.Commands.Advanced.Links;

namespace RevitBridge.Commands.Advanced
{
    /// <summary>
    /// Registry for Phase 2 commands (51 professional tools)
    /// High-value additions for advanced professional workflows
    /// </summary>
    public static class Phase2CommandRegistry
    {
        public static object Execute(UIApplication app, string tool, JsonElement payload)
        {
            return tool switch
            {
                // === GEOMETRY COMMANDS (20 tools) - Advanced Modeling ===
                // ElementTransformUtils (#3, Score: 286), JoinGeometryUtils (#10, Score: 280)

                "revit.get_element_geometry" => GeometryCommands.GetElementGeometry(app, payload),
                "revit.get_element_faces" => GeometryCommands.GetElementFaces(app, payload),
                "revit.get_element_edges" => GeometryCommands.GetElementEdges(app, payload),
                "revit.join_geometry" => GeometryCommands.JoinGeometry(app, payload),
                "revit.unjoin_geometry" => GeometryCommands.UnjoinGeometry(app, payload),
                "revit.cut_geometry" => GeometryCommands.CutGeometry(app, payload),
                "revit.array_elements_linear" => GeometryCommands.ArrayElementsLinear(app, payload),
                "revit.array_elements_radial" => GeometryCommands.ArrayElementsRadial(app, payload),
                "revit.align_elements" => GeometryCommands.AlignElements(app, payload),
                "revit.distribute_elements" => GeometryCommands.DistributeElements(app, payload),
                "revit.offset_curves" => GeometryCommands.OffsetCurves(app, payload),
                "revit.create_direct_shape" => GeometryCommands.CreateDirectShape(app, payload),
                "revit.create_solid_extrusion" => GeometryCommands.CreateSolidExtrusion(app, payload),
                "revit.create_solid_revolution" => GeometryCommands.CreateSolidRevolution(app, payload),
                "revit.create_solid_sweep" => GeometryCommands.CreateSolidSweep(app, payload),
                "revit.create_solid_blend" => GeometryCommands.CreateSolidBlend(app, payload),
                "revit.boolean_union" => GeometryCommands.BooleanUnion(app, payload),
                "revit.boolean_intersect" => GeometryCommands.BooleanIntersect(app, payload),
                "revit.boolean_subtract" => GeometryCommands.BooleanSubtract(app, payload),
                "revit.create_curve_loop" => GeometryCommands.CreateCurveLoop(app, payload),

                // === FAMILY COMMANDS (12 tools) - Content Management ===
                // Family (#17, Score: 272), FamilySymbol (#18, Score: 271)

                "revit.load_family" => FamilyCommands.LoadFamily(app, payload),
                "revit.reload_family" => FamilyCommands.ReloadFamily(app, payload),
                "revit.duplicate_family_type" => FamilyCommands.DuplicateFamilyType(app, payload),
                "revit.rename_family_type" => FamilyCommands.RenameFamilyType(app, payload),
                "revit.set_family_type_parameter" => FamilyCommands.SetFamilyTypeParameter(app, payload),
                "revit.get_nested_families" => FamilyCommands.GetNestedFamilies(app, payload),
                "revit.replace_family" => FamilyCommands.ReplaceFamily(app, payload),
                "revit.transfer_standards" => FamilyCommands.TransferStandards(app, payload),
                "revit.purge_unused_families" => FamilyCommands.PurgeUnusedFamilies(app, payload),
                "revit.get_family_category" => FamilyCommands.GetFamilyCategory(app, payload),
                "revit.list_family_instances" => FamilyCommands.ListFamilyInstances(app, payload),
                "revit.swap_family_type" => FamilyCommands.SwapFamilyType(app, payload),

                // === WORKSHARING COMMANDS (10 tools) - Collaboration ===
                // WorksharingUtils (#16, Score: 273)

                "revit.create_workset" => WorksharingCommands.CreateWorkset(app, payload),
                "revit.rename_workset" => WorksharingCommands.RenameWorkset(app, payload),
                "revit.set_element_workset" => WorksharingCommands.SetElementWorkset(app, payload),
                "revit.get_element_workset" => WorksharingCommands.GetElementWorkset(app, payload),
                "revit.checkout_elements" => WorksharingCommands.CheckoutElements(app, payload),
                "revit.get_workset_owner" => WorksharingCommands.GetWorksetOwner(app, payload),
                "revit.enable_worksharing" => WorksharingCommands.EnableWorksharing(app, payload),
                "revit.get_central_path" => WorksharingCommands.GetCentralPath(app, payload),
                "revit.set_workset_visibility" => WorksharingCommands.SetWorksetVisibility(app, payload),
                "revit.get_workset_visibility" => WorksharingCommands.GetWorksetVisibility(app, payload),

                // === LINK COMMANDS (9 tools) - Integration ===
                // RevitLinkType (#19, Score: 267), RevitLinkInstance (#20, Score: 266)

                "revit.load_link" => LinkCommands.LoadLink(app, payload),
                "revit.unload_link" => LinkCommands.UnloadLink(app, payload),
                "revit.reload_link" => LinkCommands.ReloadLink(app, payload),
                "revit.get_link_transform" => LinkCommands.GetLinkTransform(app, payload),
                "revit.set_link_visibility" => LinkCommands.SetLinkVisibility(app, payload),
                "revit.import_cad" => LinkCommands.ImportCAD(app, payload),
                "revit.manage_cad_import" => LinkCommands.ManageCADImport(app, payload),
                "revit.bind_link" => LinkCommands.BindLink(app, payload),
                "revit.get_link_elements_advanced" => LinkCommands.GetLinkElementsAdvanced(app, payload),

                _ => null // Return null to let main factory handle unknown commands
            };
        }

        /// <summary>
        /// Get list of all Phase 2 command names for documentation/validation
        /// </summary>
        public static string[] GetCommandNames()
        {
            return new[]
            {
                // Geometry (20)
                "revit.get_element_geometry",
                "revit.get_element_faces",
                "revit.get_element_edges",
                "revit.join_geometry",
                "revit.unjoin_geometry",
                "revit.cut_geometry",
                "revit.array_elements_linear",
                "revit.array_elements_radial",
                "revit.align_elements",
                "revit.distribute_elements",
                "revit.offset_curves",
                "revit.create_direct_shape",
                "revit.create_solid_extrusion",
                "revit.create_solid_revolution",
                "revit.create_solid_sweep",
                "revit.create_solid_blend",
                "revit.boolean_union",
                "revit.boolean_intersect",
                "revit.boolean_subtract",
                "revit.create_curve_loop",

                // Families (12)
                "revit.load_family",
                "revit.reload_family",
                "revit.duplicate_family_type",
                "revit.rename_family_type",
                "revit.set_family_type_parameter",
                "revit.get_nested_families",
                "revit.replace_family",
                "revit.transfer_standards",
                "revit.purge_unused_families",
                "revit.get_family_category",
                "revit.list_family_instances",
                "revit.swap_family_type",

                // Worksharing (10)
                "revit.create_workset",
                "revit.rename_workset",
                "revit.set_element_workset",
                "revit.get_element_workset",
                "revit.checkout_elements",
                "revit.get_workset_owner",
                "revit.enable_worksharing",
                "revit.get_central_path",
                "revit.set_workset_visibility",
                "revit.get_workset_visibility",

                // Links (9)
                "revit.load_link",
                "revit.unload_link",
                "revit.reload_link",
                "revit.get_link_transform",
                "revit.set_link_visibility",
                "revit.import_cad",
                "revit.manage_cad_import",
                "revit.bind_link",
                "revit.get_link_elements_advanced"
            };
        }
    }
}
