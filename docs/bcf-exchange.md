# BCF issue exchange

Two tools move issues in and out of the standard BCF 2.1 `.bcfzip` format:

- `bcf_exchange_export_bcf` saves a list of issues, and optionally the issues recorded by the QA/QC checker, to a `.bcfzip` file in your workspace folder.
- `bcf_exchange_import_bcf` reads a `.bcfzip` from your workspace folder and returns the issues (title, description, status, priority, assigned to, element ids).

Each issue can carry `title`, `description`, `status`, `priority`, `author`, `assigned_to`, `element_uids` (Revit UniqueIds) and `ifc_guids`. Neither tool changes the Revit model.

## Safety

Files must be inside the allowed workspace directories. When reading, the zip is never unpacked to disk. Files with paths that climb out of the archive, absolute paths, symbolic links, too many entries or oversized content (zip bombs) are refused, as is any XML that declares a DOCTYPE or entity (which blocks entity expansion and external-file tricks).

## Not verified

The BCF layout was written from general knowledge of BCF 2.1. It has **not** been validated against buildingSMART's XSD schemas, and files have **not** been opened in Revit, Solibri, BIMcollab, Navisworks or any other BCF tool. Treat interoperability as UNVERIFIED. Revit UniqueIds are not IFC GUIDs, so they are stored as the authoring-tool id of a component; only IFC GUIDs given as `ifc_guids` are written as `IfcGuid`. Viewpoints contain a component selection only (no camera).
