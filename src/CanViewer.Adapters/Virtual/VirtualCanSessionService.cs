using CanViewer.Adapters.Internal;
using CanViewer.Core.Services;

namespace CanViewer.Adapters.Virtual;

public sealed class VirtualCanSessionService : LoopbackCanSessionServiceBase
{
    protected override CanInterfaceKind InterfaceKind => CanInterfaceKind.Virtual;

    public VirtualCanSessionService(int queueCapacity = 200_000) : base(queueCapacity)
    {
    }

    protected override CanChannelScanResult ScanOwnInterfaceChannels() => ScanProfiles.ForVirtual();
}
