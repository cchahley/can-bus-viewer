namespace CanViewer.Core.Services;

public sealed record CanSendResult(
    bool Success,
    string Message
);
