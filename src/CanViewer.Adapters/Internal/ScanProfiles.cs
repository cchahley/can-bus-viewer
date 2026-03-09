using CanViewer.Core.Services;

namespace CanViewer.Adapters.Internal;

internal static class ScanProfiles
{
    public static CanChannelScanResult ForVirtual()
    {
        return new CanChannelScanResult(
            new[] { "0" },
            "0",
            true,
            "Virtual CAN available (loopback mode)."
        );
    }

    public static CanChannelScanResult ForPcan()
    {
        return new CanChannelScanResult(
            new[] { "PCAN_USBBUS1", "PCAN_USBBUS2" },
            "PCAN_USBBUS1",
            true,
            "PCAN scaffold: select channel manually (vendor SDK wiring pending)."
        );
    }

    public static CanChannelScanResult ForVector()
    {
        return new CanChannelScanResult(
            new[] { "0", "1" },
            "0",
            true,
            "Vector scaffold: select channel index manually (vendor SDK wiring pending)."
        );
    }

    public static CanChannelScanResult ForSlcan()
    {
        // COM3 default mirrors python fallback while hardware probing is being ported.
        return new CanChannelScanResult(
            new[] { "COM3" },
            "COM3",
            true,
            "SLCAN scaffold: choose serial port (automatic serial enumeration pending)."
        );
    }
}
