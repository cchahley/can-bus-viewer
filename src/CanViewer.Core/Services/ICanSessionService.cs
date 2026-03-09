using CanViewer.Core.Models;

namespace CanViewer.Core.Services;

public interface ICanSessionService : IAsyncDisposable
{
    bool IsConnected { get; }
    long DroppedFrameCount { get; }

    ValueTask<CanChannelScanResult> ScanChannelsAsync(CanInterfaceKind kind, CancellationToken cancellationToken = default);
    ValueTask<(bool Success, string Message)> ConnectAsync(CanConnectionOptions options, CancellationToken cancellationToken = default);
    ValueTask DisconnectAsync(CancellationToken cancellationToken = default);
    ValueTask<CanSendResult> SendAsync(CanFrame frame, CancellationToken cancellationToken = default);

    IAsyncEnumerable<CanFrame> ReadFramesAsync(CancellationToken cancellationToken = default);
}
