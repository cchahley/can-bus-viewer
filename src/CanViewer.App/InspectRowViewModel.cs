using CommunityToolkit.Mvvm.ComponentModel;

namespace CanViewer.App;

public sealed partial class InspectRowViewModel : ObservableObject
{
    [ObservableProperty] private string _timestamp = string.Empty;
    [ObservableProperty] private string _relativeSeconds = string.Empty;
    [ObservableProperty] private string _arbitrationIdHex = string.Empty;
    [ObservableProperty] private string _rawDataHex = string.Empty;
    [ObservableProperty] private string _symbolic = string.Empty;

    public static InspectRowViewModel Create(string timestamp, string relativeSeconds, string arbitrationIdHex, string rawDataHex, string symbolic)
    {
        return new InspectRowViewModel
        {
            Timestamp = timestamp,
            RelativeSeconds = relativeSeconds,
            ArbitrationIdHex = arbitrationIdHex,
            RawDataHex = rawDataHex,
            Symbolic = symbolic
        };
    }
}
