namespace CanViewer.Core.Services;

public sealed record CanConnectionOptions(
    CanInterfaceKind Interface,
    string Channel,
    int Bitrate
);
