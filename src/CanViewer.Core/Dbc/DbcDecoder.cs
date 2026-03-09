using System.Globalization;
using CanViewer.Core.Models;

namespace CanViewer.Core.Dbc;

public sealed record DecodedSignalValue(
    string MessageName,
    string SignalName,
    string Value,
    double NumericValue,
    string Unit
);

public static class DbcDecoder
{
    public static IReadOnlyList<DecodedSignalValue> Decode(CanFrame frame, DbcDatabase database)
    {
        if (!database.MessagesByArbitrationId.TryGetValue(frame.ArbitrationId, out var message))
        {
            return Array.Empty<DecodedSignalValue>();
        }

        var bytes = frame.Data.ToArray();
        var decoded = new List<DecodedSignalValue>(message.Signals.Count);
        foreach (var signal in message.Signals)
        {
            if (signal.Length <= 0 || signal.Length > 64)
            {
                continue;
            }

            var raw = signal.IsLittleEndian
                ? ExtractLittleEndianRaw(bytes, signal.StartBit, signal.Length)
                : ExtractBigEndianRaw(bytes, signal.StartBit, signal.Length);

            double physical;
            if (signal.IsSigned)
            {
                var signedRaw = ToSigned(raw, signal.Length);
                physical = (signedRaw * signal.Factor) + signal.Offset;
            }
            else
            {
                physical = (raw * signal.Factor) + signal.Offset;
            }

            var unitSuffix = string.IsNullOrWhiteSpace(signal.Unit) ? string.Empty : $" {signal.Unit}";
            decoded.Add(new DecodedSignalValue(
                message.Name,
                signal.Name,
                $"{physical.ToString("G", CultureInfo.InvariantCulture)}{unitSuffix}",
                physical,
                signal.Unit
            ));
        }

        return decoded;
    }

    private static ulong ExtractLittleEndianRaw(byte[] data, int startBit, int length)
    {
        ulong value = 0;
        for (var i = 0; i < length; i++)
        {
            var bitIndex = startBit + i;
            var bit = GetDbcBit(data, bitIndex);
            value |= bit << i;
        }

        return value;
    }

    private static ulong ExtractBigEndianRaw(byte[] data, int startBit, int length)
    {
        ulong value = 0;
        var bitIndex = startBit;
        for (var i = 0; i < length; i++)
        {
            var bit = GetDbcBit(data, bitIndex);
            value = (value << 1) | bit;
            bitIndex = NextBigEndianBit(bitIndex);
        }

        return value;
    }

    private static int NextBigEndianBit(int currentBit)
    {
        // DBC big-endian uses sawtooth numbering across bytes.
        return (currentBit & 0x7) == 0
            ? currentBit + 15
            : currentBit - 1;
    }

    private static ulong GetDbcBit(byte[] data, int bitIndex)
    {
        if (bitIndex < 0)
        {
            return 0;
        }

        var byteIndex = bitIndex / 8;
        if (byteIndex < 0 || byteIndex >= data.Length)
        {
            return 0;
        }

        var bitInByte = bitIndex % 8;
        return (ulong)((data[byteIndex] >> bitInByte) & 0x1);
    }

    private static long ToSigned(ulong raw, int bitLength)
    {
        if (bitLength <= 0 || bitLength >= 64)
        {
            return unchecked((long)raw);
        }

        var signBit = 1UL << (bitLength - 1);
        if ((raw & signBit) == 0)
        {
            return (long)raw;
        }

        var fullScale = 1UL << bitLength;
        return (long)(raw - fullScale);
    }
}
