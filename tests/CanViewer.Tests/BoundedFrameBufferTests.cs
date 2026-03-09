using CanViewer.Core.Buffers;
using CanViewer.Core.Models;

namespace CanViewer.Tests;

public class BoundedFrameBufferTests
{
    [Fact]
    public void Add_WhenCapacityExceeded_DropsOldest()
    {
        var buffer = new BoundedFrameBuffer(2);

        buffer.Add(NewFrame(0x100, 0x01));
        buffer.Add(NewFrame(0x101, 0x02));
        buffer.Add(NewFrame(0x102, 0x03));

        var snapshot = buffer.Snapshot();
        Assert.Equal(2, snapshot.Count);
        Assert.Equal((uint)0x101, snapshot[0].ArbitrationId);
        Assert.Equal((uint)0x102, snapshot[1].ArbitrationId);
        Assert.Equal(1, buffer.DroppedCount);
    }

    private static CanFrame NewFrame(uint id, byte value)
    {
        return new CanFrame(
            DateTimeOffset.UtcNow,
            id,
            1,
            new byte[] { value }
        );
    }
}
