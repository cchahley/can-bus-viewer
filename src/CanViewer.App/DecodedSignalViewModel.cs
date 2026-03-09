using CommunityToolkit.Mvvm.ComponentModel;

namespace CanViewer.App;

public sealed partial class DecodedSignalViewModel : ObservableObject
{
    [ObservableProperty] private string _signalName = string.Empty;
    [ObservableProperty] private string _value = string.Empty;
    [ObservableProperty] private string _unit = string.Empty;
    [ObservableProperty] private string _minimum = string.Empty;
    [ObservableProperty] private string _maximum = string.Empty;
}
