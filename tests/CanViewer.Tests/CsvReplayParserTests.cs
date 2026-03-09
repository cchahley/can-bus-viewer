using CanViewer.Core.Replay;

namespace CanViewer.Tests;

public class CsvReplayParserTests
{
    [Fact]
    public void Parse_ValidRows_ProducesReplayEntries()
    {
        var csv = """
            rel_seconds,arb_id_hex,data_hex
            0.000,0x123,01020304
            0.050,0x100,AA55
            """;

        var entries = CsvReplayParser.Parse(csv);

        Assert.Equal(2, entries.Count);
        Assert.Equal((uint)0x123, entries[0].Frame.ArbitrationId);
        Assert.Equal((byte)4, entries[0].Frame.Dlc);
        Assert.Equal((uint)0x100, entries[1].Frame.ArbitrationId);
        Assert.Equal((byte)2, entries[1].Frame.Dlc);
    }
}
