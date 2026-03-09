using System.Collections.Concurrent;
using System.Runtime.InteropServices;
using System.Text;
using CanViewer.Core.Models;
using CanViewer.Core.Services;

namespace CanViewer.Adapters.Pcan;

public sealed class PcanCanSessionService : ICanSessionService
{
    private static readonly (ushort Handle, string Name)[] KnownUsbChannels =
    [
        (0x51, "PCAN_USBBUS1"),
        (0x52, "PCAN_USBBUS2"),
        (0x53, "PCAN_USBBUS3"),
        (0x54, "PCAN_USBBUS4"),
        (0x55, "PCAN_USBBUS5"),
        (0x56, "PCAN_USBBUS6"),
        (0x57, "PCAN_USBBUS7"),
        (0x58, "PCAN_USBBUS8"),
        (0x509, "PCAN_USBBUS9"),
        (0x50A, "PCAN_USBBUS10"),
        (0x50B, "PCAN_USBBUS11"),
        (0x50C, "PCAN_USBBUS12"),
        (0x50D, "PCAN_USBBUS13"),
        (0x50E, "PCAN_USBBUS14"),
        (0x50F, "PCAN_USBBUS15"),
        (0x510, "PCAN_USBBUS16")
    ];

    private readonly ConcurrentQueue<CanFrame> _rxQueue = new();
    private readonly SemaphoreSlim _rxSignal = new(0);
    private readonly object _stateLock = new();
    private CancellationTokenSource? _readerCts;
    private Task? _readerTask;
    private ushort _channelHandle = 0x51;

    public bool IsConnected { get; private set; }
    public long DroppedFrameCount { get; private set; }

    public ValueTask<CanChannelScanResult> ScanChannelsAsync(CanInterfaceKind kind, CancellationToken cancellationToken = default)
    {
        if (kind != CanInterfaceKind.Pcan)
        {
            return ValueTask.FromResult(
                new CanChannelScanResult(Array.Empty<string>(), null, false, "Service is bound to PCAN."));
        }

        if (!Native.TryLoad())
        {
            return ValueTask.FromResult(
                new CanChannelScanResult(
                    Channels: Array.Empty<string>(),
                    DefaultChannel: null,
                    CanConnect: false,
                    Status: "PCANBasic.dll not found. Install PEAK PCAN-Basic/driver package."
                ));
        }

        var available = new List<string>();
        foreach (var channel in KnownUsbChannels)
        {
            var status = Native.GetStatus(channel.Handle);
            if (status == Native.PCAN_ERROR_OK || status == Native.PCAN_ERROR_BUSOFF || status == Native.PCAN_ERROR_BUSHEAVY)
            {
                available.Add(channel.Name);
            }
        }

        if (available.Count == 0)
        {
            available.Add("PCAN_USBBUS1");
            return ValueTask.FromResult(
                new CanChannelScanResult(available, "PCAN_USBBUS1", true, "PCAN available. Connect using configured channel."));
        }

        return ValueTask.FromResult(
            new CanChannelScanResult(available, available[0], true, $"Detected {available.Count} PCAN channel(s)."));
    }

    public ValueTask<(bool Success, string Message)> ConnectAsync(CanConnectionOptions options, CancellationToken cancellationToken = default)
    {
        if (options.Interface != CanInterfaceKind.Pcan)
        {
            return ValueTask.FromResult((false, "PCAN service only supports PCAN interface."));
        }

        if (!Native.TryLoad())
        {
            return ValueTask.FromResult((false, "PCANBasic.dll not found. Install PEAK driver/PCAN-Basic."));
        }

        var handle = ParseHandle(options.Channel);
        var baud = MapBitrate(options.Bitrate);
        if (baud == 0)
        {
            return ValueTask.FromResult((false, $"Unsupported PCAN bitrate: {options.Bitrate}"));
        }

        lock (_stateLock)
        {
            if (IsConnected)
            {
                _ = DisconnectAsync(cancellationToken);
            }

            var initStatus = Native.Initialize(handle, baud);
            if (initStatus != Native.PCAN_ERROR_OK)
            {
                return ValueTask.FromResult((false, $"PCAN init failed: {Native.FormatError(initStatus)}"));
            }

            _channelHandle = handle;
            IsConnected = true;
            _readerCts = new CancellationTokenSource();
            _readerTask = Task.Run(() => ReaderLoop(_readerCts.Token));
        }

        return ValueTask.FromResult((true, $"Connected: PCAN {FormatHandle(_channelHandle)} @ {options.Bitrate}"));
    }

    public async ValueTask DisconnectAsync(CancellationToken cancellationToken = default)
    {
        CancellationTokenSource? cts = null;
        Task? readerTask = null;
        ushort channel = 0;
        lock (_stateLock)
        {
            if (!IsConnected)
            {
                return;
            }

            IsConnected = false;
            cts = _readerCts;
            readerTask = _readerTask;
            _readerCts = null;
            _readerTask = null;
            channel = _channelHandle;
        }

        if (cts is not null)
        {
            cts.Cancel();
            cts.Dispose();
        }

        if (readerTask is not null)
        {
            try
            {
                await readerTask.ConfigureAwait(false);
            }
            catch (OperationCanceledException)
            {
            }
        }

        _ = Native.Uninitialize(channel);
    }

    public ValueTask<CanSendResult> SendAsync(CanFrame frame, CancellationToken cancellationToken = default)
    {
        if (!IsConnected)
        {
            return ValueTask.FromResult(new CanSendResult(false, "Not connected."));
        }

        var data = frame.Data.ToArray();
        if (data.Length > 8)
        {
            return ValueTask.FromResult(new CanSendResult(false, "PCAN supports classic CAN payload length <= 8 bytes."));
        }

        var message = new Native.TPCANMsg
        {
            ID = frame.ArbitrationId,
            LEN = (byte)data.Length,
            DATA = new byte[8]
        };

        Array.Copy(data, message.DATA, data.Length);
        if (frame.IsExtendedId)
        {
            message.MSGTYPE |= Native.PCAN_MESSAGE_EXTENDED;
        }

        if (frame.IsRemoteFrame)
        {
            message.MSGTYPE |= Native.PCAN_MESSAGE_RTR;
        }

        var status = Native.Write(_channelHandle, ref message);
        if (status != Native.PCAN_ERROR_OK)
        {
            return ValueTask.FromResult(new CanSendResult(false, $"PCAN send failed: {Native.FormatError(status)}"));
        }

        return ValueTask.FromResult(new CanSendResult(true, "Sent"));
    }

    public async IAsyncEnumerable<CanFrame> ReadFramesAsync([System.Runtime.CompilerServices.EnumeratorCancellation] CancellationToken cancellationToken = default)
    {
        while (!cancellationToken.IsCancellationRequested)
        {
            while (_rxQueue.TryDequeue(out var frame))
            {
                yield return frame;
            }

            await _rxSignal.WaitAsync(TimeSpan.FromMilliseconds(20), cancellationToken).ConfigureAwait(false);
        }
    }

    public async ValueTask DisposeAsync()
    {
        await DisconnectAsync().ConfigureAwait(false);
        _rxSignal.Dispose();
    }

    private async Task ReaderLoop(CancellationToken cancellationToken)
    {
        while (!cancellationToken.IsCancellationRequested && IsConnected)
        {
            var status = Native.Read(_channelHandle, out var message, out _);
            if (status == Native.PCAN_ERROR_QRCVEMPTY)
            {
                await Task.Delay(1, cancellationToken).ConfigureAwait(false);
                continue;
            }

            if (status != Native.PCAN_ERROR_OK)
            {
                await Task.Delay(2, cancellationToken).ConfigureAwait(false);
                continue;
            }

            var isExtended = (message.MSGTYPE & Native.PCAN_MESSAGE_EXTENDED) != 0;
            var isRemote = (message.MSGTYPE & Native.PCAN_MESSAGE_RTR) != 0;
            var isError = (message.MSGTYPE & Native.PCAN_MESSAGE_ERRFRAME) != 0;
            var dlc = Math.Clamp(message.LEN, (byte)0, (byte)8);
            var data = message.DATA.Take(dlc).ToArray();

            var frame = new CanFrame(
                TimestampUtc: DateTimeOffset.UtcNow,
                ArbitrationId: message.ID,
                Dlc: dlc,
                Data: data,
                IsExtendedId: isExtended,
                IsRemoteFrame: isRemote,
                IsErrorFrame: isError
            );

            _rxQueue.Enqueue(frame);
            _rxSignal.Release();
        }
    }

    private static ushort ParseHandle(string channel)
    {
        if (string.IsNullOrWhiteSpace(channel))
        {
            return 0x51;
        }

        var clean = channel.Trim().ToUpperInvariant();
        foreach (var known in KnownUsbChannels)
        {
            if (clean == known.Name)
            {
                return known.Handle;
            }
        }

        clean = clean
            .Replace("PCAN_USB", string.Empty, StringComparison.Ordinal)
            .Replace("USBBUS", string.Empty, StringComparison.Ordinal)
            .Replace("BUS", string.Empty, StringComparison.Ordinal);

        if (ushort.TryParse(clean, out var number) && number >= 1 && number <= 16)
        {
            return KnownUsbChannels[number - 1].Handle;
        }

        if (clean.StartsWith("0X", StringComparison.OrdinalIgnoreCase) &&
            ushort.TryParse(clean.AsSpan(2), System.Globalization.NumberStyles.HexNumber, null, out var hex))
        {
            return hex;
        }

        return 0x51;
    }

    private static string FormatHandle(ushort handle)
    {
        var match = KnownUsbChannels.FirstOrDefault(x => x.Handle == handle);
        return string.IsNullOrEmpty(match.Name) ? $"0x{handle:X}" : match.Name;
    }

    private static ushort MapBitrate(int bitrate) => bitrate switch
    {
        1000000 => 0x0014,
        800000 => 0x0016,
        500000 => 0x001C,
        250000 => 0x011C,
        125000 => 0x031C,
        100000 => 0x432F,
        95000 => 0xC34E,
        83000 => 0x852B,
        50000 => 0x472F,
        47000 => 0x1414,
        33000 => 0x8B2F,
        20000 => 0x532F,
        10000 => 0x672F,
        5000 => 0x7F7F,
        _ => 0
    };

    private static class Native
    {
        public const uint PCAN_ERROR_OK = 0x00000;
        public const uint PCAN_ERROR_QRCVEMPTY = 0x00020;
        public const uint PCAN_ERROR_BUSHEAVY = 0x00008;
        public const uint PCAN_ERROR_BUSOFF = 0x00010;
        public const byte PCAN_MESSAGE_EXTENDED = 0x02;
        public const byte PCAN_MESSAGE_RTR = 0x01;
        public const byte PCAN_MESSAGE_ERRFRAME = 0x40;

        private static bool? _loaded;

        [StructLayout(LayoutKind.Sequential)]
        public struct TPCANMsg
        {
            public uint ID;
            public byte MSGTYPE;
            public byte LEN;

            [MarshalAs(UnmanagedType.ByValArray, SizeConst = 8)]
            public byte[] DATA;
        }

        [StructLayout(LayoutKind.Sequential)]
        public struct TPCANTimestamp
        {
            public uint millis;
            public ushort millis_overflow;
            public ushort micros;
        }

        [DllImport("PCANBasic.dll", EntryPoint = "CAN_Initialize")]
        private static extern uint CanInitialize(ushort channel, ushort btr0Btr1, uint hwType, uint ioPort, ushort interrupt);

        [DllImport("PCANBasic.dll", EntryPoint = "CAN_Uninitialize")]
        private static extern uint CanUninitialize(ushort channel);

        [DllImport("PCANBasic.dll", EntryPoint = "CAN_GetStatus")]
        private static extern uint CanGetStatus(ushort channel);

        [DllImport("PCANBasic.dll", EntryPoint = "CAN_Read")]
        private static extern uint CanRead(ushort channel, out TPCANMsg message, out TPCANTimestamp timestamp);

        [DllImport("PCANBasic.dll", EntryPoint = "CAN_Write")]
        private static extern uint CanWrite(ushort channel, ref TPCANMsg message);

        [DllImport("PCANBasic.dll", EntryPoint = "CAN_GetErrorText", CharSet = CharSet.Ansi)]
        private static extern uint CanGetErrorText(uint error, ushort language, StringBuilder buffer);

        public static bool TryLoad()
        {
            if (_loaded.HasValue)
            {
                return _loaded.Value;
            }

            try
            {
                _ = CanGetStatus(0x51);
                _loaded = true;
            }
            catch (DllNotFoundException)
            {
                _loaded = false;
            }
            catch (BadImageFormatException)
            {
                _loaded = false;
            }
            catch (EntryPointNotFoundException)
            {
                _loaded = false;
            }

            return _loaded.Value;
        }

        public static uint Initialize(ushort channel, ushort btr0Btr1)
        {
            try
            {
                return CanInitialize(channel, btr0Btr1, 0, 0, 0);
            }
            catch
            {
                return 0x20000;
            }
        }

        public static uint Uninitialize(ushort channel)
        {
            try
            {
                return CanUninitialize(channel);
            }
            catch
            {
                return 0x20000;
            }
        }

        public static uint GetStatus(ushort channel)
        {
            try
            {
                return CanGetStatus(channel);
            }
            catch
            {
                return 0x20000;
            }
        }

        public static uint Read(ushort channel, out TPCANMsg message, out TPCANTimestamp timestamp)
        {
            message = default;
            timestamp = default;
            try
            {
                return CanRead(channel, out message, out timestamp);
            }
            catch
            {
                return 0x20000;
            }
        }

        public static uint Write(ushort channel, ref TPCANMsg message)
        {
            try
            {
                return CanWrite(channel, ref message);
            }
            catch
            {
                return 0x20000;
            }
        }

        public static string FormatError(uint error)
        {
            var buffer = new StringBuilder(256);
            try
            {
                var status = CanGetErrorText(error, 0, buffer);
                if (status == PCAN_ERROR_OK)
                {
                    return buffer.ToString();
                }
            }
            catch
            {
            }

            return $"0x{error:X}";
        }
    }
}
