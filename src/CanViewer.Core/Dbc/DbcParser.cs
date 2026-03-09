using System.Globalization;
using System.Text.RegularExpressions;

namespace CanViewer.Core.Dbc;

public static partial class DbcParser
{
    [GeneratedRegex(@"^BO_\s+(?<id>\d+)\s+(?<name>[^:]+)\s*:\s*(?<dlc>\d+)\s+\S+")]
    private static partial Regex MessageRegex();

    [GeneratedRegex(@"^SG_\s+(?<name>[A-Za-z0-9_]+)(?:\s+\S+)?\s*:\s*(?<start>\d+)\|(?<length>\d+)@(?<byteorder>[01])(?<sign>[+-])\s+\((?<factor>[-+]?\d*\.?\d+(?:[eE][-+]?\d+)?),(?<offset>[-+]?\d*\.?\d+(?:[eE][-+]?\d+)?)\)\s+\[[^\]]*\]\s+""(?<unit>[^""]*)""")]
    private static partial Regex SignalRegex();

    public static DbcDatabase Parse(string dbcContent)
    {
        var messages = new Dictionary<uint, DbcMessageDefinition>();
        DbcMessageBuilder? current = null;

        foreach (var rawLine in dbcContent.Split('\n'))
        {
            var line = rawLine.Trim();
            if (line.Length == 0 || line.StartsWith("CM_", StringComparison.Ordinal) || line.StartsWith("BA_", StringComparison.Ordinal))
            {
                continue;
            }

            var messageMatch = MessageRegex().Match(line);
            if (messageMatch.Success)
            {
                var rawId = uint.Parse(messageMatch.Groups["id"].Value, CultureInfo.InvariantCulture);
                var normalized = NormalizeDbcId(rawId);
                var name = messageMatch.Groups["name"].Value.Trim();
                var dlc = int.Parse(messageMatch.Groups["dlc"].Value, CultureInfo.InvariantCulture);
                current = new DbcMessageBuilder(name, normalized.ArbitrationId, dlc, normalized.IsExtendedId);
                messages[current.ArbitrationId] = current.Build();
                continue;
            }

            if (current is null || !line.StartsWith("SG_", StringComparison.Ordinal))
            {
                continue;
            }

            var signalMatch = SignalRegex().Match(line);
            if (!signalMatch.Success)
            {
                continue;
            }

            var signal = new DbcSignalDefinition(
                Name: signalMatch.Groups["name"].Value,
                StartBit: int.Parse(signalMatch.Groups["start"].Value, CultureInfo.InvariantCulture),
                Length: int.Parse(signalMatch.Groups["length"].Value, CultureInfo.InvariantCulture),
                IsLittleEndian: signalMatch.Groups["byteorder"].Value == "1",
                IsSigned: signalMatch.Groups["sign"].Value == "-",
                Factor: double.Parse(signalMatch.Groups["factor"].Value, CultureInfo.InvariantCulture),
                Offset: double.Parse(signalMatch.Groups["offset"].Value, CultureInfo.InvariantCulture),
                Unit: signalMatch.Groups["unit"].Value
            );

            current.Signals.Add(signal);
            messages[current.ArbitrationId] = current.Build();
        }

        return new DbcDatabase(messages);
    }

    private static (uint ArbitrationId, bool IsExtendedId) NormalizeDbcId(uint rawId)
    {
        // DBC files often encode 29-bit frame ids with bit 31 set.
        if ((rawId & 0x80000000) != 0)
        {
            return (rawId & 0x1FFFFFFF, true);
        }

        return (rawId, rawId > 0x7FF);
    }

    private sealed class DbcMessageBuilder(string name, uint arbitrationId, int dlc, bool isExtendedId)
    {
        public string Name { get; } = name;
        public uint ArbitrationId { get; } = arbitrationId;
        public int Dlc { get; } = dlc;
        public bool IsExtendedId { get; } = isExtendedId;
        public List<DbcSignalDefinition> Signals { get; } = [];

        public DbcMessageDefinition Build() => new(
            Name,
            ArbitrationId,
            Dlc,
            IsExtendedId,
            Signals.ToArray()
        );
    }
}
