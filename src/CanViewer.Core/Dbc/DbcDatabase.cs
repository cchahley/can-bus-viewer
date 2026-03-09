namespace CanViewer.Core.Dbc;

public sealed record DbcSignalDefinition(
    string Name,
    int StartBit,
    int Length,
    bool IsLittleEndian,
    bool IsSigned,
    double Factor,
    double Offset,
    string Unit
);

public sealed record DbcMessageDefinition(
    string Name,
    uint ArbitrationId,
    int Dlc,
    bool IsExtendedId,
    IReadOnlyList<DbcSignalDefinition> Signals
);

public sealed class DbcDatabase
{
    public static DbcDatabase Empty { get; } = new(new Dictionary<uint, DbcMessageDefinition>());

    public DbcDatabase(IReadOnlyDictionary<uint, DbcMessageDefinition> messagesByArbitrationId)
    {
        MessagesByArbitrationId = messagesByArbitrationId;
    }

    public IReadOnlyDictionary<uint, DbcMessageDefinition> MessagesByArbitrationId { get; }

    public static DbcDatabase Merge(IEnumerable<DbcDatabase> databases)
    {
        var merged = new Dictionary<uint, DbcMessageDefinition>();
        foreach (var database in databases)
        {
            foreach (var kvp in database.MessagesByArbitrationId)
            {
                // Last loaded DBC wins on arbitration-id collisions.
                merged[kvp.Key] = kvp.Value;
            }
        }

        return new DbcDatabase(merged);
    }
}
