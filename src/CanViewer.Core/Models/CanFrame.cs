namespace CanViewer.Core.Models;

public readonly record struct CanFrame(
    DateTimeOffset TimestampUtc,
    uint ArbitrationId,
    byte Dlc,
    ReadOnlyMemory<byte> Data,
    bool IsExtendedId = false,
    bool IsRemoteFrame = false,
    bool IsErrorFrame = false
);
