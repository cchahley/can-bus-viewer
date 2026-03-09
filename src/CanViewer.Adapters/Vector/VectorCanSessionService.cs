using CanViewer.Adapters.Internal;
using CanViewer.Core.Services;

namespace CanViewer.Adapters.Vector;

public sealed class VectorCanSessionService : LoopbackCanSessionServiceBase
{
    protected override CanInterfaceKind InterfaceKind => CanInterfaceKind.Vector;

    protected override CanChannelScanResult ScanOwnInterfaceChannels() => ScanProfiles.ForVector();
}
