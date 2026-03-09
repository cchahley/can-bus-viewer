using CanViewer.Adapters.Virtual;
using CanViewer.Core.Models;
using CanViewer.Core.Services;

namespace CanViewer.Tests;

public class VirtualCanSessionServiceTests
{
    [Fact]
    public async Task Send_WhenConnected_FrameCanBeReadBack()
    {
        await using var session = new VirtualCanSessionService();

        var connect = await session.ConnectAsync(new CanConnectionOptions(CanInterfaceKind.Virtual, "0", 500000));
        Assert.True(connect.Success);

        var frame = new CanFrame(
            DateTimeOffset.UtcNow,
            0x123,
            2,
            new byte[] { 0xAA, 0x55 }
        );

        var send = await session.SendAsync(frame);
        Assert.True(send.Success);

        using var cts = new CancellationTokenSource(TimeSpan.FromSeconds(2));
        await foreach (var read in session.ReadFramesAsync(cts.Token))
        {
            Assert.Equal(frame.ArbitrationId, read.ArbitrationId);
            Assert.Equal(frame.Dlc, read.Dlc);
            Assert.Equal(frame.Data.ToArray(), read.Data.ToArray());
            return;
        }

        Assert.Fail("No frame read from virtual session.");
    }
}
