# Canonical Test Model

P17.1 is script-first: do not commit generated RVT binaries here.

Run from the repository root while Revit is open with the AEC Model Bridge add-in loaded:

```powershell
python scripts\revit\generate_canonical_test_model.py
```

The script discovers the active Revit bridge from `%LOCALAPPDATA%\AECModelBridge\registry\`, falls back to `http://127.0.0.1:3000`, and saves to `fixtures/canonical-model/generated/canonical_test_model.rvt`.

If the bridge-created document is not activated by Revit, open a clean project template yourself and rerun with `--use-active-document`.
