using CanViewer.Adapters.Pcan;
using CanViewer.Adapters.Slcan;
using CanViewer.Adapters.Virtual;
using CanViewer.Adapters.Vector;
using CanViewer.Core.Services;

namespace CanViewer.Adapters;

public static class CanSessionServiceFactory
{
    public static ICanSessionService Create(CanInterfaceKind preferredInterface)
    {
        return preferredInterface switch
        {
            CanInterfaceKind.Pcan => new PcanCanSessionService(),
            CanInterfaceKind.Vector => new VectorCanSessionService(),
            CanInterfaceKind.Slcan => new SlcanCanSessionService(),
            _ => new VirtualCanSessionService()
        };
    }
}
