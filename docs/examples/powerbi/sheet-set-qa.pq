// Sheet set QA findings. Source: sheet_set_qa_check with csv_filename "qa/sheet_set_qa.csv".
// Needs a text parameter named WorkspaceFolder (see docs/powerbi-qa-dashboard.md).
// UNVERIFIED in Power BI Desktop.
let
    RequiredColumns = {"severity", "check", "sheet_number", "sheet_name", "unique_id", "detail", "next_step"},
    Path = Text.TrimEnd(WorkspaceFolder, "\") & "\qa\sheet_set_qa.csv",
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
    // The exporter prefixes a text cell that starts with = + - or @ with an apostrophe.
    Unescape = (v as any) as any =>
        if v is text and Text.Length(v) > 1 and Text.StartsWith(v, "'") and Text.Contains("=+-@", Text.Middle(v, 1, 1))
        then Text.Middle(v, 1) else v,
    Cleaned = Table.TransformColumns(Checked, List.Transform(RequiredColumns, each {_, Unescape, type text})),
    Result = Table.SelectColumns(Cleaned, RequiredColumns)
in
    Result
