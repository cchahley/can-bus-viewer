using System.Globalization;
using CanViewer.Core.Models;

namespace CanViewer.Core.Dbc;

public static class DbcEncoder
{
    public static (bool Success, CanFrame Frame, string Message) TryEncode(
        DbcMessageDefinition message,
        IReadOnlyDictionary<string, double> signalValues)
    {
        var data = new byte[Math.Clamp(message.Dlc, 0, 8)];
        foreach (var signal in message.Signals)
        {
            if (!signalValues.TryGetValue(signal.Name, out var physical))
            {
                continue;
            }

            var rawDouble = (physical - signal.Offset) / signal.Factor;
            var rawSigned = (long)Math.Round(rawDouble, MidpointRounding.AwayFromZero);
            ulong raw;
            if (signal.IsSigned)
            {
                if (signal.Length <= 0 || signal.Length > 63)
                {
                    return (false, default, $"Signal {signal.Name} length unsupported.");
                }

                var min = -(1L << (signal.Length - 1));
                var max = (1L << (signal.Length - 1)) - 1;
                if (rawSigned < min || rawSigned > max)
                {
                    return (false, default, $"Signal {signal.Name} value out of range.");
                }

                raw = (ulong)(rawSigned < 0 ? (1L << signal.Length) + rawSigned : rawSigned);
            }
            else
            {
                if (rawSigned < 0)
                {
                    return (false, default, $"Signal {signal.Name} cannot be negative.");
                }

                raw = (ulong)rawSigned;
            }

            if (signal.IsLittleEndian)
            {
                InsertLittleEndianRaw(data, signal.StartBit, signal.Length, raw);
            }
            else
            {
                InsertBigEndianRaw(data, signal.StartBit, signal.Length, raw);
            }
        }

        var frame = new CanFrame(
            TimestampUtc: DateTimeOffset.UtcNow,
            ArbitrationId: message.ArbitrationId,
            Dlc: (byte)data.Length,
            Data: data,
            IsExtendedId: message.IsExtendedId
        );

        return (true, frame, "Encoded");
    }

    public static (bool Success, IReadOnlyDictionary<string, double> Values, string Message) ParseKeyValueInput(string text)
    {
        var dict = new Dictionary<string, double>(StringComparer.Ordinal);
        if (string.IsNullOrWhiteSpace(text))
        {
            return (true, dict, "Empty value set.");
        }

        var parts = text.Split([',', ';', '\n', '\r'], StringSplitOptions.RemoveEmptyEntries | StringSplitOptions.TrimEntries);
        foreach (var part in parts)
        {
            var eqIndex = part.IndexOf('=');
            if (eqIndex <= 0 || eqIndex >= part.Length - 1)
            {
                return (false, dict, $"Invalid symbolic token: {part}");
            }

            var name = part[..eqIndex].Trim();
            var valueText = part[(eqIndex + 1)..].Trim();
            if (!double.TryParse(valueText, NumberStyles.Float, CultureInfo.InvariantCulture, out var value))
            {
                return (false, dict, $"Invalid symbolic value for {name}: {valueText}");
            }

            dict[name] = value;
        }

        return (true, dict, "Parsed");
    }

    private static void InsertLittleEndianRaw(byte[] data, int startBit, int length, ulong raw)
    {
        for (var i = 0; i < length; i++)
        {
            var bit = (raw >> i) & 0x1;
            SetDbcBit(data, startBit + i, bit);
        }
    }

    private static void InsertBigEndianRaw(byte[] data, int startBit, int length, ulong raw)
    {
        var bitIndex = startBit;
        for (var i = length - 1; i >= 0; i--)
        {
            var bit = (raw >> i) & 0x1;
            SetDbcBit(data, bitIndex, bit);
            bitIndex = NextBigEndianBit(bitIndex);
        }
    }

    private static int NextBigEndianBit(int currentBit)
    {
        return (currentBit & 0x7) == 0
            ? currentBit + 15
            : currentBit - 1;
    }

    private static void SetDbcBit(byte[] data, int bitIndex, ulong bit)
    {
        if (bitIndex < 0)
        {
            return;
        }

        var byteIndex = bitIndex / 8;
        if (byteIndex < 0 || byteIndex >= data.Length)
        {
            return;
        }

        var bitInByte = bitIndex % 8;
        var mask = (byte)(1 << bitInByte);
        if (bit != 0)
        {
            data[byteIndex] |= mask;
        }
        else
        {
            data[byteIndex] &= (byte)~mask;
        }
    }
}
