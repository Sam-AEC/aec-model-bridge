# Changelog — Detailed Parametric Façade System

All notable changes to the parametric façade scripts in this directory are documented here.

## [2026-06-14] — Dynamo Sandbox Alignment & Visual Graph Generation

### Added
*   **Dynamo Graph Generator (`facade_dyn_builder.py`):** Rewrote the script to generate a fully organized, structured, and complete Dynamo Sandbox graph (`facade_system.dyn`) that aligns 100% with the Grasshopper layout and capabilities.
*   **Visual Group Annotations:** Implemented 9 semi-transparent colored Annotation groups (Grid & Bays, Structural Profiles, Glazing, Gaskets, Slab & Anchors, Engine, Extract Channels, Material Swatches, and Render Pipeline) to neatly lay out and document the graph.
*   **Detailed Geometry (PolyCurve Extrusion):** Updated the embedded Python node geometry code to construct detailed chamfered cover caps for mullions and transoms, matching the exact physical profile dimensions and chamfers used in Rhino.
*   **Native Performance Calculator:** Programmatically built a native calculator inside a Code Block node, wired directly to Watch nodes on the canvas to display total glazed area and estimated cost in real-time.
*   **JSON Syntax Corrections:** Resolved `NameError: name 'false' is not defined` compile errors by using Python native booleans (`True` and `False`) in the dictionary representations which serialize correctly.

## [2026-06-14] — Initial Release of Detailed Stick Curtain Wall System


### Added
*   `detailed_facade.py`: The core geometry script implementing realistic stick curtain wall components (hollow aluminum profiles, double glazing (IGUs) with spacer frames and sealant pockets, EPDM gaskets, polyamide thermal breaks, pressure plates, cover caps, slab anchors, concrete slabs).
*   `run_facade_bridge.py`: Runner utility to compile and push the detailed facade script directly to the active Rhino session via port 3004.
*   `facade_gh_builder.py`: Metaprogramming script to generate a structured Grasshopper canvas with 4 grouped sliders and wire them to a Python component.
*   `CHANGELOG.md`: Project changelog for script additions and updates.

## [2026-06-14] — Refinement & Python 3 Migration (Audited & Corrected)

### Fixed
*   **Gasket-Glazing Intersections:** Resolved physical Y-depth overlaps by implementing a sequential coordinate mapping from interior (Y > 0) to exterior (Y < 0). Gaskets are now compressed tightly against profiles and glass surfaces without colliding.
*   **Gasket Sizing:** Sized gaskets parametrically in the X/Z directions based on `GLASS_REVEAL` and `GASKET_W` parameters to stay neat and prevent protruding past profile shoulders.

### Added
*   **Rhino 8 Python 3 Migration:** Migrated the canvas builder to instantiate the new **Python 3 Script** component (`RhinoCodePluginGH.Components.Python3Component`) using CPython 3 in Rhino 8. Programmed fallback and direct `.SetSource()` execution.
*   **Native Performance Calculator:** Programmatically built a native math graph (Multiplication components, panels, scribbles) on the canvas to calculate total glazed area and facade cost from the sliders.
*   **Material Legend & Specification Panels:** Added technical description panels next to swatches to document specs (U-values, materials, glass properties) directly on the canvas.
*   **Scribble Groups:** Programmed bold visual headers above each parameter group to structure the visual canvas.

## [2026-06-14] — Parametric Detailing & Interop Fixes (Refined & Corrected)

### Fixed
*   **Data Interop Conversion Warnings:** Resolved `Data conversion failed from Goo to Geometry` by using .NET `List[rg.Brep]` inside the CPython 3 script so Grasshopper unpacks it directly to geometric branches. Resolved `Number to Colour` warnings by targeting explicit Math Multiplication GUIDs instead of color multipliers. Fixed color swatches by using `.SwatchColour` property instead of `.Value`.
*   **Dynamic Gasket Widths:** Derived gasket widths dynamically as `profile_width * 0.5 - GLASS_REVEAL` instead of a hardcoded value. Gaskets now dynamically resize when profile widths or glass reveals are dragged, preventing visual gaps and overlaps.

### Added
*   **Boundary Transoms:** Added closed Sill and Head transoms at the extreme boundaries (`z = 0.0` and `z = TOTAL_HEIGHT`) to terminate the curtain wall system structurally.
*   **Continuous Spandrels:** Omitted intermediate slab-level splits in the glazing layout, resolving floating seam joints and merging the glass into a single continuous panel zone.
*   **Boundary Gasket Filtering:** Filtered out gaskets at top/bottom system boundaries where no glazing panel exists.

