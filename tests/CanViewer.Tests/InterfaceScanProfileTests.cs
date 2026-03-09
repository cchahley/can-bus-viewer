using CanViewer.Adapters;
using CanViewer.Core.Services;

namespace CanViewer.Tests;

public class InterfaceScanProfileTests
{
    [Theory]
    [InlineData(CanInterfaceKind.Pcan, "PCAN_USBBUS1")]
    [InlineData(CanInterfaceKind.Vector, "0")]
    [InlineData(CanInterfaceKind.Slcan, "COM3")]
    [InlineData(CanInterfaceKind.Virtual, "0")]
    public async Task Scan_ReturnsDefaultChannel(CanInterfaceKind kind, string expectedDefault)
    {
        await using var session = CanSessionServiceFactory.Create(kind);
        var result = await session.ScanChannelsAsync(kind);

        Assert.True(result.CanConnect);
        Assert.NotNull(result.DefaultChannel);
        Assert.Equal(expectedDefault, result.DefaultChannel);
        Assert.NotEmpty(result.Channels);
    }
}
