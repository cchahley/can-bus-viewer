using System.Globalization;
using CanViewer.Adapters;
using CanViewer.Core.Models;
using CanViewer.Core.Replay;
using CanViewer.Core.Services;
using CanViewer.Core.Triggers;
using Microsoft.UI.Xaml;
using Microsoft.UI.Xaml.Controls;
using Windows.Storage.Pickers;

namespace CanViewer.App;

public sealed partial class MainWindow : Window
{
    private readonly MainWindowViewModel _viewModel = new();
    private readonly Dictionary<Guid, CancellationTokenSource> _cardPeriodicSendCts = [];
    private CancellationTokenSource? _readerCts;
    private CancellationTokenSource? _replayCts;
    private CancellationTokenSource? _periodicSendCts;

    public MainWindow()
    {
        InitializeComponent();
        _viewModel.DispatcherQueue = DispatcherQueue;
        RootGrid.DataContext = _viewModel;

        InterfaceComboBox.ItemsSource = Enum.GetNames<CanInterfaceKind>();
        InterfaceComboBox.SelectedIndex = 3; // Virtual
        BitrateComboBox.SelectedItem = "500000";
        RawModeComboBox.SelectedIndex = 0;
        InspectModeComboBox.SelectedIndex = 0;
        TriggerOperatorComboBox.ItemsSource = Enum.GetNames<TriggerOperator>();
        TriggerOperatorComboBox.SelectedItem = nameof(TriggerOperator.Equal);
        DecodeWatchComboBox.ItemsSource = _viewModel.DecodeWatchOptions;
        DecodeWatchListView.ItemsSource = _viewModel.DecodeWatchItems;
        if (_viewModel.SymbolicCards.Count == 0)
        {
            _ = _viewModel.AddSymbolicCard();
        }
        _ = ScanCurrentInterfaceAsync();
    }

    private CanInterfaceKind SelectedInterface
    {
        get
        {
            if (InterfaceComboBox.SelectedItem is string text &&
                Enum.TryParse<CanInterfaceKind>(text, ignoreCase: true, out var parsed))
            {
                return parsed;
            }

            return CanInterfaceKind.Virtual;
        }
    }

    private int SelectedBitrate
    {
        get
        {
            var raw = (BitrateComboBox.SelectedItem as string) ?? BitrateComboBox.Text;
            return int.TryParse(raw, out var value) ? value : 500000;
        }
    }

    private string SelectedChannel
    {
        get
        {
            var fromSelected = ChannelComboBox.SelectedItem as string;
            var value = string.IsNullOrWhiteSpace(fromSelected) ? ChannelComboBox.Text : fromSelected;
            return string.IsNullOrWhiteSpace(value) ? "0" : value.Trim();
        }
    }

    private async Task ScanCurrentInterfaceAsync()
    {
        var iface = SelectedInterface;
        await using var scanSession = CanSessionServiceFactory.Create(iface);
        var scan = await scanSession.ScanChannelsAsync(iface);

        ChannelComboBox.ItemsSource = scan.Channels;
        ChannelComboBox.SelectedItem = scan.DefaultChannel;
        ChannelComboBox.Text = scan.DefaultChannel ?? string.Empty;
        _viewModel.StatusText = scan.Status;
    }

    private async void OnScanClick(object sender, RoutedEventArgs e)
    {
        await ScanCurrentInterfaceAsync();
    }

    private async void OnConnectClick(object sender, RoutedEventArgs e)
    {
        var iface = SelectedInterface;

        if (_viewModel.Session is not null && _viewModel.Session.IsConnected)
        {
            await _viewModel.Session.DisconnectAsync();
        }

        _viewModel.Session = CanSessionServiceFactory.Create(iface);
        var options = new CanConnectionOptions(iface, SelectedChannel, SelectedBitrate);
        var result = await _viewModel.Session.ConnectAsync(options);
        _viewModel.StatusText = result.Message;
        if (!result.Success)
        {
            return;
        }

        _readerCts?.Cancel();
        _readerCts = new CancellationTokenSource();
        _ = _viewModel.StartReadingAsync(_readerCts.Token);
        _ = StartStatusRefreshAsync(_readerCts.Token);
    }

    private async void OnDisconnectClick(object sender, RoutedEventArgs e)
    {
        _readerCts?.Cancel();
        _replayCts?.Cancel();
        _periodicSendCts?.Cancel();
        StopAllCardPeriodic();
        if (_viewModel.Session is not null)
        {
            await _viewModel.Session.DisconnectAsync();
            _viewModel.StatusText = "Disconnected";
        }
    }

    private async void OnSendRawFrameClick(object sender, RoutedEventArgs e)
    {
        if (_viewModel.Session is null || !_viewModel.Session.IsConnected)
        {
            _viewModel.StatusText = "Connect first.";
            return;
        }

        if (!TryParseHexId(SendArbIdTextBox.Text, out var arbId))
        {
            _viewModel.StatusText = "Invalid arbitration ID.";
            return;
        }

        if (!TryParseHexBytes(SendDataTextBox.Text, out var data))
        {
            _viewModel.StatusText = "Invalid data bytes.";
            return;
        }

        var frame = new CanFrame(
            TimestampUtc: DateTimeOffset.UtcNow,
            ArbitrationId: arbId,
            Dlc: (byte)data.Length,
            Data: data,
            IsExtendedId: SendExtendedCheckBox.IsChecked == true
        );

        var result = await _viewModel.Session.SendAsync(frame);
        _viewModel.StatusText = result.Message;
    }

    private void OnStartPeriodicSendClick(object sender, RoutedEventArgs e)
    {
        if (SendPeriodicCheckBox.IsChecked != true)
        {
            _viewModel.StatusText = "Enable Periodic first.";
            return;
        }

        if (!int.TryParse(SendPeriodMsTextBox.Text, out var periodMs) || periodMs < 5)
        {
            _viewModel.StatusText = "Invalid period (min 5 ms).";
            return;
        }

        _periodicSendCts?.Cancel();
        _periodicSendCts = new CancellationTokenSource();
        _ = RunPeriodicSendAsync(periodMs, _periodicSendCts.Token);
        _viewModel.StatusText = $"Periodic send started ({periodMs} ms).";
    }

    private void OnStopPeriodicSendClick(object sender, RoutedEventArgs e)
    {
        _periodicSendCts?.Cancel();
        _viewModel.StatusText = "Periodic send stopped.";
    }

    private async void OnAddDbcClick(object sender, RoutedEventArgs e)
    {
        var typedPath = DbcPathTextBox.Text.Trim();
        if (!string.IsNullOrWhiteSpace(typedPath))
        {
            var typedResult = _viewModel.AddDbcFile(typedPath);
            _viewModel.StatusText = typedResult.Message;
            EnsureAtLeastOneCard();
            return;
        }

        var picker = new FileOpenPicker();
        picker.FileTypeFilter.Add(".dbc");
        picker.FileTypeFilter.Add("*");
        picker.SuggestedStartLocation = PickerLocationId.DocumentsLibrary;

        var hwnd = WinRT.Interop.WindowNative.GetWindowHandle(this);
        WinRT.Interop.InitializeWithWindow.Initialize(picker, hwnd);
        var files = await picker.PickMultipleFilesAsync();
        if (files is null || files.Count == 0)
        {
            _viewModel.StatusText = "DBC selection canceled.";
            return;
        }

        var loaded = 0;
        string lastMessage = "No DBC loaded.";
        foreach (var file in files)
        {
            var result = _viewModel.AddDbcFile(file.Path);
            if (result.Success)
            {
                loaded++;
            }

            lastMessage = result.Message;
        }

        _viewModel.StatusText = loaded > 0
            ? $"Loaded {loaded} DBC file(s)."
            : lastMessage;
        EnsureAtLeastOneCard();
    }

    private void OnRemoveDbcClick(object sender, RoutedEventArgs e)
    {
        if (DbcFilesListView.SelectedItem is not DbcFileRowViewModel row)
        {
            _viewModel.StatusText = "Select a DBC file first.";
            return;
        }

        var result = _viewModel.RemoveDbcFile(row.Path);
        _viewModel.StatusText = result.Message;
        EnsureAtLeastOneCard();
    }

    private void OnAddSymbolicCardClick(object sender, RoutedEventArgs e)
    {
        _ = _viewModel.AddSymbolicCard();
    }

    private void OnCardMessageChanged(object sender, SelectionChangedEventArgs e)
    {
        if (sender is ComboBox combo &&
            combo.DataContext is SymbolicSendCardViewModel card &&
            combo.SelectedItem is string display)
        {
            _viewModel.SetCardMessage(card.Id, display);
        }
    }

    private async void OnCardSendClick(object sender, RoutedEventArgs e)
    {
        if (_viewModel.Session is null || !_viewModel.Session.IsConnected)
        {
            _viewModel.StatusText = "Connect first.";
            return;
        }

        if (sender is not Button { DataContext: SymbolicSendCardViewModel card })
        {
            return;
        }

        var encode = _viewModel.TryBuildCardFrame(card.Id);
        if (!encode.Success)
        {
            _viewModel.StatusText = $"Symbolic send failed: {encode.Message}";
            return;
        }

        var send = await _viewModel.Session.SendAsync(encode.Frame);
        _viewModel.StatusText = send.Success ? $"Symbolic message sent: {card.MessageDisplay}" : send.Message;
    }

    private void OnCardRemoveClick(object sender, RoutedEventArgs e)
    {
        if (sender is not Button { DataContext: SymbolicSendCardViewModel card })
        {
            return;
        }

        StopCardPeriodic(card.Id);
        _viewModel.RemoveSymbolicCard(card.Id);
    }

    private void OnCardPeriodicChecked(object sender, RoutedEventArgs e)
    {
        if (sender is not CheckBox { DataContext: SymbolicSendCardViewModel card })
        {
            return;
        }

        if (_viewModel.Session is null || !_viewModel.Session.IsConnected)
        {
            _viewModel.StatusText = "Connect first for periodic symbolic send.";
            card.IsPeriodic = false;
            return;
        }

        StopCardPeriodic(card.Id);
        var period = Math.Max(5, card.PeriodMs);
        var cts = new CancellationTokenSource();
        _cardPeriodicSendCts[card.Id] = cts;
        _ = RunCardPeriodicSendAsync(card.Id, period, cts.Token);
    }

    private void OnCardPeriodicUnchecked(object sender, RoutedEventArgs e)
    {
        if (sender is CheckBox { DataContext: SymbolicSendCardViewModel card })
        {
            StopCardPeriodic(card.Id);
        }
    }

    private void OnAddDecodeWatchClick(object sender, RoutedEventArgs e)
    {
        if (DecodeWatchComboBox.SelectedItem is string display)
        {
            _viewModel.AddDecodeWatch(display);
            _viewModel.StatusText = $"Watching decode message: {display}";
        }
    }

    private void OnRemoveDecodeWatchClick(object sender, RoutedEventArgs e)
    {
        if (DecodeWatchListView.SelectedItem is string display)
        {
            _viewModel.RemoveDecodeWatch(display);
            _viewModel.StatusText = $"Removed watch: {display}";
        }
    }

    private void OnClearDecodeWatchClick(object sender, RoutedEventArgs e)
    {
        _viewModel.ClearDecodeWatch();
        _viewModel.StatusText = "Decode watch cleared.";
    }

    private void OnPauseClick(object sender, RoutedEventArgs e)
    {
        _viewModel.SetPaused(true);
        _viewModel.StatusText = "Paused.";
    }

    private void OnPlayClick(object sender, RoutedEventArgs e)
    {
        _viewModel.SetPaused(false);
        _viewModel.StatusText = "Live.";
    }

    private void OnRawModeChanged(object sender, SelectionChangedEventArgs e)
    {
        _viewModel.SetRawMode(RawModeComboBox.SelectedIndex == 1 ? DisplayRowMode.LatestPerId : DisplayRowMode.AllFrames);
    }

    private void OnInspectModeChanged(object sender, SelectionChangedEventArgs e)
    {
        _viewModel.SetInspectMode(InspectModeComboBox.SelectedIndex == 1 ? DisplayRowMode.LatestPerId : DisplayRowMode.AllFrames);
    }

    private void OnClearAllClick(object sender, RoutedEventArgs e)
    {
        _viewModel.ClearAll();
        UpdateStatsLabels();
    }

    private void OnLoadReplayClick(object sender, RoutedEventArgs e)
    {
        try
        {
            var path = ReplayPathTextBox.Text.Trim();
            if (!File.Exists(path))
            {
                _viewModel.StatusText = "Replay file not found.";
                return;
            }

            var content = File.ReadAllText(path);
            var entries = CsvReplayParser.Parse(content);
            _viewModel.LoadReplayEntries(entries);
            _viewModel.StatusText = $"Loaded {entries.Count} replay frame(s).";
        }
        catch (Exception ex)
        {
            _viewModel.StatusText = $"Replay load failed: {ex.Message}";
        }
    }

    private void OnStartReplayClick(object sender, RoutedEventArgs e)
    {
        if (_viewModel.Session is null || !_viewModel.Session.IsConnected)
        {
            _viewModel.StatusText = "Connect first.";
            return;
        }

        _replayCts?.Cancel();
        _replayCts = new CancellationTokenSource();
        _ = _viewModel.ReplayAsync(_replayCts.Token);
        _viewModel.StatusText = "Replay started.";
    }

    private void OnStopReplayClick(object sender, RoutedEventArgs e)
    {
        _replayCts?.Cancel();
        _viewModel.StatusText = "Replay stopped.";
    }

    private void OnAddTriggerClick(object sender, RoutedEventArgs e)
    {
        if (!TryParseHexId(TriggerArbIdTextBox.Text, out var arbId))
        {
            _viewModel.StatusText = "Invalid trigger arbitration ID.";
            return;
        }

        if (!int.TryParse(TriggerByteIndexTextBox.Text, out var byteIndex))
        {
            _viewModel.StatusText = "Invalid trigger byte index.";
            return;
        }

        if (!double.TryParse(TriggerThresholdTextBox.Text, NumberStyles.Float, CultureInfo.InvariantCulture, out var threshold))
        {
            _viewModel.StatusText = "Invalid trigger threshold.";
            return;
        }

        if (TriggerOperatorComboBox.SelectedItem is not string opText ||
            !Enum.TryParse<TriggerOperator>(opText, out var triggerOp))
        {
            _viewModel.StatusText = "Invalid trigger operator.";
            return;
        }

        var added = _viewModel.AddTriggerRule(arbId, byteIndex, triggerOp, threshold);
        _viewModel.StatusText = added ? "Trigger added." : "Trigger add failed.";
    }

    private void OnRemoveTriggerClick(object sender, RoutedEventArgs e)
    {
        if (TriggerListView.SelectedItem is TriggerRowViewModel row)
        {
            _viewModel.RemoveTriggerRule(row.Id);
            _viewModel.StatusText = "Trigger removed.";
        }
    }

    private async Task StartStatusRefreshAsync(CancellationToken cancellationToken)
    {
        try
        {
            while (!cancellationToken.IsCancellationRequested)
            {
                await Task.Delay(250, cancellationToken);
                DispatcherQueue.TryEnqueue(() =>
                {
                    UpdateStatsLabels();
                    if (AutoScrollCheckBox.IsChecked == true &&
                        _viewModel.RawRows.Count > 0 &&
                        _viewModel.RawMode == DisplayRowMode.AllFrames &&
                        MainPivot.SelectedItem is PivotItem { Header: "Raw" })
                    {
                        RawListView.ScrollIntoView(_viewModel.RawRows[^1]);
                    }
                });
            }
        }
        catch (OperationCanceledException)
        {
        }
    }

    private async Task RunPeriodicSendAsync(int periodMs, CancellationToken cancellationToken)
    {
        while (!cancellationToken.IsCancellationRequested)
        {
            await DispatcherQueue.EnqueueAsync(async () =>
            {
                OnSendRawFrameClick(this, new RoutedEventArgs());
                await Task.CompletedTask;
            });

            await Task.Delay(periodMs, cancellationToken);
        }
    }

    private async Task RunCardPeriodicSendAsync(Guid cardId, int periodMs, CancellationToken cancellationToken)
    {
        while (!cancellationToken.IsCancellationRequested)
        {
            await DispatcherQueue.EnqueueAsync(async () =>
            {
                if (_viewModel.Session is null || !_viewModel.Session.IsConnected)
                {
                    return;
                }

                var encode = _viewModel.TryBuildCardFrame(cardId);
                if (!encode.Success)
                {
                    _viewModel.StatusText = $"Card periodic encode failed: {encode.Message}";
                    return;
                }

                var send = await _viewModel.Session.SendAsync(encode.Frame);
                if (!send.Success)
                {
                    _viewModel.StatusText = $"Card periodic send failed: {send.Message}";
                }
            });

            await Task.Delay(periodMs, cancellationToken);
        }
    }

    private void EnsureAtLeastOneCard()
    {
        if (_viewModel.SymbolicCards.Count == 0 && _viewModel.SymbolicMessageOptions.Count > 0)
        {
            _ = _viewModel.AddSymbolicCard();
        }
    }

    private void StopCardPeriodic(Guid cardId)
    {
        if (_cardPeriodicSendCts.TryGetValue(cardId, out var cts))
        {
            cts.Cancel();
            cts.Dispose();
            _cardPeriodicSendCts.Remove(cardId);
        }
    }

    private void StopAllCardPeriodic()
    {
        foreach (var cts in _cardPeriodicSendCts.Values)
        {
            cts.Cancel();
            cts.Dispose();
        }
        _cardPeriodicSendCts.Clear();
    }

    private void UpdateStatsLabels()
    {
        MessageCountText.Text = _viewModel.MessageCount.ToString(CultureInfo.InvariantCulture);
        TriggerCountText.Text = _viewModel.TriggerHitCount.ToString(CultureInfo.InvariantCulture);
        DroppedCountText.Text = _viewModel.Session?.DroppedFrameCount.ToString(CultureInfo.InvariantCulture) ?? "0";
        QueueDepthText.Text = _viewModel.RenderQueueDepth.ToString(CultureInfo.InvariantCulture);
        RenderStrideText.Text = _viewModel.RenderStride.ToString(CultureInfo.InvariantCulture);
        DecodeStrideText.Text = _viewModel.DecodeStride.ToString(CultureInfo.InvariantCulture);
        UiFlushMsText.Text = _viewModel.LastUiFlushMs.ToString("F1", CultureInfo.InvariantCulture);
        SampledOutText.Text = _viewModel.SampledOutFrameCount.ToString(CultureInfo.InvariantCulture);
    }

    private static bool TryParseHexId(string input, out uint value)
    {
        var compact = input.Trim().Replace("0x", string.Empty, StringComparison.OrdinalIgnoreCase);
        return uint.TryParse(compact, NumberStyles.HexNumber, CultureInfo.InvariantCulture, out value);
    }

    private static bool TryParseHexBytes(string input, out byte[] bytes)
    {
        var compact = input.Replace(" ", string.Empty).Replace("-", string.Empty);
        if (compact.Length == 0 || compact.Length % 2 != 0)
        {
            bytes = Array.Empty<byte>();
            return false;
        }

        bytes = new byte[compact.Length / 2];
        for (var i = 0; i < bytes.Length; i++)
        {
            if (!byte.TryParse(
                compact.AsSpan(i * 2, 2),
                NumberStyles.HexNumber,
                CultureInfo.InvariantCulture,
                out bytes[i]))
            {
                bytes = Array.Empty<byte>();
                return false;
            }
        }

        return true;
    }
}

internal static class DispatcherQueueExtensions
{
    public static Task EnqueueAsync(this Microsoft.UI.Dispatching.DispatcherQueue dispatcherQueue, Func<Task> callback)
    {
        var tcs = new TaskCompletionSource<object?>();
        dispatcherQueue.TryEnqueue(async () =>
        {
            try
            {
                await callback().ConfigureAwait(false);
                tcs.TrySetResult(null);
            }
            catch (Exception ex)
            {
                tcs.TrySetException(ex);
            }
        });

        return tcs.Task;
    }
}
