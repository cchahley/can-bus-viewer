using System.Collections.ObjectModel;
using CommunityToolkit.Mvvm.ComponentModel;

namespace CanViewer.App;

public sealed partial class SymbolicSendCardViewModel : ObservableObject
{
    public Guid Id { get; init; } = Guid.NewGuid();

    [ObservableProperty] private string _title = "DBC Message";
    [ObservableProperty] private string _messageDisplay = string.Empty;
    [ObservableProperty] private bool _isPeriodic;
    [ObservableProperty] private int _periodMs = 100;

    public ObservableCollection<string> MessageOptions { get; } = new();
    public ObservableCollection<SymbolicSignalInputViewModel> Signals { get; } = new();
}
