namespace CanViewer.Core.Services;

public sealed record CanChannelScanResult(
    IReadOnlyList<string> Channels,
    string? DefaultChannel,
    bool CanConnect,
    string Status
);
