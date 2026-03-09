using CanViewer.Core.Models;
using System.Globalization;

namespace CanViewer.Core.Replay;

public static class CsvReplayParser
{
    // Supported CSV format:
    // rel_seconds,arb_id_hex,data_hex
    // 0.000,0x123,01020304
    public static IReadOnlyList<ReplayEntry> Parse(string content)
    {
        var result = new List<ReplayEntry>();
        using var reader = new StringReader(content);

        string? line;
        var index = 0;
        while ((line = reader.ReadLine()) is not null)
        {
            if (string.IsNullOrWhiteSpace(line))
            {
                continue;
            }

            var trimmed = line.Trim();
            if (trimmed.StartsWith('#') || trimmed.StartsWith("rel_seconds", StringComparison.OrdinalIgnoreCase))
            {
                continue;
            }

            var parts = trimmed.Split(',', StringSplitOptions.TrimEntries);
            if (parts.Length < 3)
            {
                continue;
            }

            if (!double.TryParse(parts[0], NumberStyles.Float, CultureInfo.InvariantCulture, out var relSeconds))
            {
                continue;
            }

            var idText = parts[1].Replace("0x", "", StringComparison.OrdinalIgnoreCase);
            if (!uint.TryParse(idText, NumberStyles.HexNumber, CultureInfo.InvariantCulture, out var arbId))
            {
                continue;
            }

            if (!TryParseHex(parts[2], out var data))
            {
                continue;
            }

            var frame = new CanFrame(
                TimestampUtc: DateTimeOffset.UtcNow,
                ArbitrationId: arbId,
                Dlc: (byte)data.Length,
                Data: data
            );
            result.Add(new ReplayEntry(index++, relSeconds, frame));
        }

        return result;
    }

    private static bool TryParseHex(string input, out byte[] bytes)
    {
        var compact = input.Replace(" ", string.Empty).Replace("-", string.Empty);
        if (compact.Length == 0 || compact.Length % 2 != 0)
        {
            bytes = Array.Empty<byte>();
            return false;
        }

        bytes = new byte[compact.Length / 2];
        for (var i = 0; i < bytes.Length; i++)
        {
            if (!byte.TryParse(
                compact.AsSpan(i * 2, 2),
                NumberStyles.HexNumber,
                CultureInfo.InvariantCulture,
                out bytes[i]))
            {
                bytes = Array.Empty<byte>();
                return false;
            }
        }

        return true;
    }
}
