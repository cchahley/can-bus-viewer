using System.Collections.ObjectModel;
using CommunityToolkit.Mvvm.ComponentModel;

namespace CanViewer.App;

public sealed partial class DecodedMessageGroupViewModel : ObservableObject
{
    [ObservableProperty] private uint _arbitrationId;
    [ObservableProperty] private string _title = string.Empty;
    [ObservableProperty] private string _arbitrationIdHex = string.Empty;
    [ObservableProperty] private string _timestamp = string.Empty;
    [ObservableProperty] private string _relativeSeconds = string.Empty;

    public ObservableCollection<DecodedSignalViewModel> Signals { get; } = new();
    public Dictionary<string, DecodedSignalViewModel> SignalByName { get; } = new(StringComparer.Ordinal);
    public Dictionary<string, (double? Min, double? Max)> SignalStats { get; } = new(StringComparer.Ordinal);
}
