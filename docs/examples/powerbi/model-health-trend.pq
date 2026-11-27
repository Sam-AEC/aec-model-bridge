// Model health trend. Source: model_health_score with csv_filename "qa/model_health.csv".
// Needs a text parameter named WorkspaceFolder (see docs/powerbi-qa-dashboard.md).
// UNVERIFIED in Power BI Desktop.
let
    RequiredColumns = {"snapshot_id", "taken_at", "score", "delta", "comparable", "partial", "warnings", "qa_findings", "unplaced_rooms", "unused_types", "completeness", "excluded"},
    Path = Text.TrimEnd(WorkspaceFolder, "\\") & "\\qa\\model_health.csv",
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
    Typed = Table.TransformColumns(Checked, {
        {"snapshot_id", each _, type text},
        {"taken_at", each let b = Blank(_) in if b = null then null else DateTimeZone.FromText(b), type datetimezone},
        {"score", ToNumber, type number}, {"delta", ToNumber, type number},
        {"comparable", ToLogical, type logical}, {"partial", ToLogical, type logical},
        {"warnings", ToNumber, type number}, {"qa_findings", ToNumber, type number},
        {"unplaced_rooms", ToNumber, type number}, {"unused_types", ToNumber, type number},
        {"completeness", ToNumber, type number}, {"excluded", each _, type text}}),
    Result = Table.SelectColumns(Typed, RequiredColumns)
in
    Result
