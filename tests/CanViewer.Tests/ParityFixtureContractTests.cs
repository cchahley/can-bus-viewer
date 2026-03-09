using System.Text.Json;

namespace CanViewer.Tests;

public class ParityFixtureContractTests
{
    [Fact]
    public void DiagFixture_HasExpectedCoreSections()
    {
        var fixturePath = Path.Combine("Fixtures", "diag_fixture.json");
        Assert.True(File.Exists(fixturePath), $"Missing fixture file: {fixturePath}");

        using var stream = File.OpenRead(fixturePath);
        using var doc = JsonDocument.Parse(stream);
        var root = doc.RootElement;

        Assert.Equal("can_viewer_diag.log", root.GetProperty("source_file").GetString());

        var summary = root.GetProperty("summary");
        Assert.True(summary.GetProperty("start_count").GetInt32() > 0);
        Assert.True(summary.GetProperty("disconnect_count").GetInt32() >= 0);
        Assert.True(summary.GetProperty("decode_error_count").GetInt32() >= 0);
    }
}
