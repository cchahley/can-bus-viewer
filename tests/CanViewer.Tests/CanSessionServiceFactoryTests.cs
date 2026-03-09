using CanViewer.Adapters;
using CanViewer.Adapters.Pcan;
using CanViewer.Adapters.Slcan;
using CanViewer.Adapters.Vector;
using CanViewer.Adapters.Virtual;
using CanViewer.Core.Services;

namespace CanViewer.Tests;

public class CanSessionServiceFactoryTests
{
    [Theory]
    [InlineData(CanInterfaceKind.Pcan, typeof(PcanCanSessionService))]
    [InlineData(CanInterfaceKind.Vector, typeof(VectorCanSessionService))]
    [InlineData(CanInterfaceKind.Slcan, typeof(SlcanCanSessionService))]
    [InlineData(CanInterfaceKind.Virtual, typeof(VirtualCanSessionService))]
    public async Task Create_ReturnsExpectedAdapter(CanInterfaceKind kind, Type expectedType)
    {
        await using var session = CanSessionServiceFactory.Create(kind);
        Assert.Equal(expectedType, session.GetType());
    }
}
