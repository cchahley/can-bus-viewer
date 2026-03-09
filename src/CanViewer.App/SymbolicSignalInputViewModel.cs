using CommunityToolkit.Mvvm.ComponentModel;

namespace CanViewer.App;

public sealed partial class SymbolicSignalInputViewModel : ObservableObject
{
    [ObservableProperty] private string _name = string.Empty;
    [ObservableProperty] private string _unit = string.Empty;
    [ObservableProperty] private string _valueText = "0";
}
