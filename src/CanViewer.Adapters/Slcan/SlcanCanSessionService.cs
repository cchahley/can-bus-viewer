using CanViewer.Adapters.Internal;
using CanViewer.Core.Services;

namespace CanViewer.Adapters.Slcan;

public sealed class SlcanCanSessionService : LoopbackCanSessionServiceBase
{
    protected override CanInterfaceKind InterfaceKind => CanInterfaceKind.Slcan;

    protected override CanChannelScanResult ScanOwnInterfaceChannels() => ScanProfiles.ForSlcan();
}
