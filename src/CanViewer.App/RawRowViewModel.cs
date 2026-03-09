using CommunityToolkit.Mvvm.ComponentModel;

namespace CanViewer.App;

public sealed partial class RawRowViewModel : ObservableObject
{
    [ObservableProperty] private string _timestamp = string.Empty;
    [ObservableProperty] private string _relativeSeconds = string.Empty;
    [ObservableProperty] private string _arbitrationIdHex = string.Empty;
    [ObservableProperty] private string _dataHex = string.Empty;

    public static RawRowViewModel Create(string timestamp, string relativeSeconds, string arbitrationIdHex, string dataHex)
    {
        return new RawRowViewModel
        {
            Timestamp = timestamp,
            RelativeSeconds = relativeSeconds,
            ArbitrationIdHex = arbitrationIdHex,
            DataHex = dataHex
        };
    }
}
