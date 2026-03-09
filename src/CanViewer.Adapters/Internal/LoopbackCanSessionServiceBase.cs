using System.Threading.Channels;
using CanViewer.Core.Models;
using CanViewer.Core.Services;

namespace CanViewer.Adapters.Internal;

public abstract class LoopbackCanSessionServiceBase : ICanSessionService
{
    private readonly Channel<CanFrame> _channel;
    private volatile bool _isConnected;

    protected LoopbackCanSessionServiceBase(int queueCapacity = 200_000)
    {
        _channel = Channel.CreateBounded<CanFrame>(new BoundedChannelOptions(queueCapacity)
        {
            FullMode = BoundedChannelFullMode.DropOldest,
            SingleReader = false,
            SingleWriter = false
        });
    }

    protected abstract CanInterfaceKind InterfaceKind { get; }

    public bool IsConnected => _isConnected;
    public long DroppedFrameCount { get; private set; }

    public ValueTask<CanChannelScanResult> ScanChannelsAsync(CanInterfaceKind kind, CancellationToken cancellationToken = default)
    {
        if (kind != InterfaceKind)
        {
            return ValueTask.FromResult(
                new CanChannelScanResult(
                    Array.Empty<string>(),
                    null,
                    false,
                    $"Service bound to {InterfaceKind}, not {kind}."
                )
            );
        }

        return ValueTask.FromResult(ScanOwnInterfaceChannels());
    }

    public ValueTask<(bool Success, string Message)> ConnectAsync(CanConnectionOptions options, CancellationToken cancellationToken = default)
    {
        if (options.Interface != InterfaceKind)
        {
            return ValueTask.FromResult((false, $"Service does not support {options.Interface}."));
        }

        var (success, message) = ValidateConnection(options);
        _isConnected = success;
        return ValueTask.FromResult((success, message));
    }

    public ValueTask DisconnectAsync(CancellationToken cancellationToken = default)
    {
        _isConnected = false;
        return ValueTask.CompletedTask;
    }

    public ValueTask<CanSendResult> SendAsync(CanFrame frame, CancellationToken cancellationToken = default)
    {
        if (!_isConnected)
        {
            return ValueTask.FromResult(new CanSendResult(false, "Not connected."));
        }

        if (!_channel.Writer.TryWrite(frame))
        {
            DroppedFrameCount++;
            return ValueTask.FromResult(new CanSendResult(false, "Frame dropped due to queue backpressure."));
        }

        return ValueTask.FromResult(new CanSendResult(true, "Sent"));
    }

    public async IAsyncEnumerable<CanFrame> ReadFramesAsync([System.Runtime.CompilerServices.EnumeratorCancellation] CancellationToken cancellationToken = default)
    {
        while (await _channel.Reader.WaitToReadAsync(cancellationToken).ConfigureAwait(false))
        {
            while (_channel.Reader.TryRead(out var frame))
            {
                yield return frame;
            }
        }
    }

    protected abstract CanChannelScanResult ScanOwnInterfaceChannels();

    protected virtual (bool Success, string Message) ValidateConnection(CanConnectionOptions options)
    {
        var channels = ScanOwnInterfaceChannels();
        if (!channels.CanConnect)
        {
            return (false, channels.Status);
        }

        if (string.IsNullOrWhiteSpace(options.Channel))
        {
            return (false, "Channel is required.");
        }

        return (true, $"Connected: {options.Interface} {options.Channel} @ {options.Bitrate}");
    }

    public ValueTask DisposeAsync()
    {
        _channel.Writer.TryComplete();
        return ValueTask.CompletedTask;
    }
}
