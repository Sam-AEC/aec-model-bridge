// Parameter completeness per category and parameter. Source: param_completeness_heatmap with
// csv_filename "qa/param_completeness.csv". "level" is written only when by_level is true.
// Needs a text parameter named WorkspaceFolder (see docs/powerbi-qa-dashboard.md).
// UNVERIFIED in Power BI Desktop.
let
    RequiredColumns = {"category", "parameter", "filled", "total", "percent"},
    OptionalColumns = {"level"},
    Path = Text.TrimEnd(WorkspaceFolder, "\\") & "\\qa\\param_completeness.csv",
    Source = Csv.Document(File.Contents(Path), [Delimiter = ",", Encoding = 65001, QuoteStyle = QuoteStyle.Csv]),
    Promoted = Table.PromoteHeaders(Source, [PromoteAllScalars = true]),
    Present = Table.ColumnNames(Promoted),
    Missing = List.Select(RequiredColumns, each not List.Contains(Present, _)),
    Checked = if List.IsEmpty(Missing)
        then Promoted
        else error Error.Record("Expression.Error", "Missing columns in " & Path, Text.Combine(Missing, ", ")),
    Blank = (v as any) as any => if v = null or v = "" then null else v,
    ToNumber = (v as any) as nullable number => let b = Blank(v) in if b = null then null else Number.FromText(b, "en-US"),
    ToLogical = (v as any) as nullable logical => let b = Blank(v) in if b = null then null else Logical.FromText(b),
    Unescape = (v as any) as any =>
        if v is text and Text.Length(v) > 1 and Text.StartsWith(v, "'") and Text.Contains("=+-@", Text.Middle(v, 1, 1))
        then Text.Middle(v, 1) else v,
    TextColumns = List.Intersect({RequiredColumns & OptionalColumns, Present}),
    Cleaned = Table.TransformColumns(Checked, List.Transform(
        List.Select(TextColumns, each _ <> "filled" and _ <> "total" and _ <> "percent"), each {_, Unescape, type text})),
    Typed = Table.TransformColumns(Cleaned, {
        {"filled", ToNumber, Int64.Type}, {"total", ToNumber, Int64.Type}, {"percent", ToNumber, type number}}),
    WithLevel = if Table.HasColumns(Typed, "level") then Typed else Table.AddColumn(Typed, "level", each null, type text),
    Result = Table.SelectColumns(WithLevel, RequiredColumns & OptionalColumns)
in
    Result
