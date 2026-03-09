namespace CanViewer.App;

public sealed record DecodedRowViewModel(
    string Timestamp,
    string MessageKey,
    string Signal,
    string Value
);
