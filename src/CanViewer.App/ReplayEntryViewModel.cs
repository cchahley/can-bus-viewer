namespace CanViewer.App;

public sealed record ReplayEntryViewModel(
    int Index,
    string RelativeSeconds,
    string ArbitrationIdHex,
    string DataHex
);
