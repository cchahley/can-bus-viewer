using System.Collections.Concurrent;
using System.Collections.ObjectModel;
using System.Diagnostics;
using System.Linq;
using CanViewer.Core.Dbc;
using CanViewer.Core.Models;
using CanViewer.Core.Replay;
using CanViewer.Core.Services;
using CanViewer.Core.Triggers;
using CommunityToolkit.Mvvm.ComponentModel;
using Microsoft.UI.Dispatching;

namespace CanViewer.App;

public partial class MainWindowViewModel : ObservableObject
{
    private string _statusText = "Ready.";
    private readonly int _maxRawRows = 3_000;
    private readonly int _maxInspectRows = 3_000;
    private readonly int _maxDecodedMessageGroups = 1_200;
    private readonly int _maxPendingFrames = 50_000;
    private readonly TriggerEvaluator _triggerEvaluator = new();
    private readonly List<ReplayEntry> _replayEntries = [];
    private readonly Dictionary<Guid, TriggerRule> _triggerRules = [];
    private readonly Dictionary<string, DbcDatabase> _dbcByPath = new(StringComparer.OrdinalIgnoreCase);
    private readonly Dictionary<string, DbcMessageDefinition> _symbolicByDisplay = new(StringComparer.Ordinal);
    private readonly Dictionary<uint, RawRowViewModel> _latestRawById = [];
    private readonly Dictionary<uint, InspectRowViewModel> _latestInspectById = [];
    private readonly Dictionary<uint, DecodedMessageGroupViewModel> _decodedGroupsById = [];
    private readonly HashSet<uint> _decodeWatchIds = [];
    private readonly ConcurrentQueue<PendingRenderFrame> _pendingFrames = new();
    private readonly ConcurrentQueue<DecodedRowViewModel> _pendingDecodedRows = new();
    private DateTimeOffset? _traceStartUtc;
    private DbcDatabase _mergedDbc = DbcDatabase.Empty;
    private volatile bool _flushScheduled;

    public string StatusText
    {
        get => _statusText;
        set => SetProperty(ref _statusText, value);
    }

    public ICanSessionService? Session { get; set; }
    public DispatcherQueue? DispatcherQueue { get; set; }

    public ObservableCollection<RawRowViewModel> RawRows { get; } = new();
    public ObservableCollection<InspectRowViewModel> InspectRows { get; } = new();
    public ObservableCollection<DecodedRowViewModel> DecodedRows { get; } = new();
    public ObservableCollection<DecodedMessageGroupViewModel> DecodedGroups { get; } = new();
    public ObservableCollection<ReplayEntryViewModel> ReplayRows { get; } = new();
    public ObservableCollection<TriggerRowViewModel> TriggerRows { get; } = new();
    public ObservableCollection<DbcFileRowViewModel> DbcFiles { get; } = new();
    public ObservableCollection<string> SymbolicMessageOptions { get; } = new();
    public ObservableCollection<SymbolicSendCardViewModel> SymbolicCards { get; } = new();
    public ObservableCollection<string> DecodeWatchOptions { get; } = new();
    public ObservableCollection<string> DecodeWatchItems { get; } = new();

    public long MessageCount { get; private set; }
    public long TriggerHitCount { get; private set; }
    public bool ReplayRunning { get; private set; }
    public bool IsPaused { get; private set; }
    public DisplayRowMode RawMode { get; private set; } = DisplayRowMode.AllFrames;
    public DisplayRowMode InspectMode { get; private set; } = DisplayRowMode.AllFrames;
    public long DroppedRenderFrameCount { get; private set; }
    public long SampledOutFrameCount { get; private set; }
    public int RenderStride { get; private set; } = 1;
    public int DecodeStride { get; private set; } = 1;
    public int RenderQueueDepth { get; private set; }
    public double LastUiFlushMs { get; private set; }

    public void ClearAll()
    {
        RawRows.Clear();
        InspectRows.Clear();
        DecodedRows.Clear();
        DecodedGroups.Clear();
        ReplayRows.Clear();
        TriggerRows.Clear();
        _latestRawById.Clear();
        _latestInspectById.Clear();
        _decodedGroupsById.Clear();
        MessageCount = 0;
        TriggerHitCount = 0;
        DroppedRenderFrameCount = 0;
        SampledOutFrameCount = 0;
        _traceStartUtc = null;
    }

    public void SetPaused(bool paused)
    {
        IsPaused = paused;
        if (paused)
        {
            while (_pendingFrames.TryDequeue(out _))
            {
            }
        }
    }

    public void SetRawMode(DisplayRowMode mode)
    {
        RawMode = mode;
        RawRows.Clear();
        _latestRawById.Clear();
    }

    public void SetInspectMode(DisplayRowMode mode)
    {
        InspectMode = mode;
        InspectRows.Clear();
        _latestInspectById.Clear();
    }

    public (bool Success, string Message) AddDbcFile(string path)
    {
        if (string.IsNullOrWhiteSpace(path))
        {
            return (false, "DBC path is required.");
        }

        if (!File.Exists(path))
        {
            return (false, "DBC file not found.");
        }

        try
        {
            var content = File.ReadAllText(path);
            var db = DbcParser.Parse(content);
            _dbcByPath[path] = db;
            RebuildMergedDbc();
            RebuildDbcFileRows();
            RebuildSymbolicOptions();
            return (true, $"Loaded DBC: {Path.GetFileName(path)} ({db.MessagesByArbitrationId.Count} message(s)).");
        }
        catch (Exception ex)
        {
            return (false, $"Failed to parse DBC: {ex.Message}");
        }
    }

    public (bool Success, string Message) RemoveDbcFile(string path)
    {
        if (!_dbcByPath.Remove(path))
        {
            return (false, "Selected DBC was not loaded.");
        }

        RebuildMergedDbc();
        RebuildDbcFileRows();
        RebuildSymbolicOptions();
        return (true, $"Removed DBC: {Path.GetFileName(path)}");
    }

    public IReadOnlyList<DbcSignalDefinition> GetSignalsForSymbolicMessage(string displayName)
    {
        return _symbolicByDisplay.TryGetValue(displayName, out var message)
            ? message.Signals
            : Array.Empty<DbcSignalDefinition>();
    }

    public (bool Success, CanFrame Frame, string Message) TryBuildSymbolicFrame(string displayName, string signalText)
    {
        if (!_symbolicByDisplay.TryGetValue(displayName, out var message))
        {
            return (false, default, "Select a symbolic message first.");
        }

        var parsed = DbcEncoder.ParseKeyValueInput(signalText);
        if (!parsed.Success)
        {
            return (false, default, parsed.Message);
        }

        return DbcEncoder.TryEncode(message, parsed.Values);
    }

    public SymbolicSendCardViewModel AddSymbolicCard()
    {
        var card = new SymbolicSendCardViewModel();
        foreach (var option in SymbolicMessageOptions)
        {
            card.MessageOptions.Add(option);
        }
        SymbolicCards.Add(card);
        if (SymbolicMessageOptions.Count > 0)
        {
            SetCardMessage(card.Id, SymbolicMessageOptions[0]);
        }
        return card;
    }

    public void RemoveSymbolicCard(Guid cardId)
    {
        var card = SymbolicCards.FirstOrDefault(x => x.Id == cardId);
        if (card is not null)
        {
            SymbolicCards.Remove(card);
        }
    }

    public void SetCardMessage(Guid cardId, string displayName)
    {
        var card = SymbolicCards.FirstOrDefault(x => x.Id == cardId);
        if (card is null)
        {
            return;
        }

        card.MessageDisplay = displayName;
        card.Title = displayName;
        card.Signals.Clear();
        foreach (var signal in GetSignalsForSymbolicMessage(displayName))
        {
            card.Signals.Add(new SymbolicSignalInputViewModel
            {
                Name = signal.Name,
                Unit = signal.Unit,
                ValueText = "0"
            });
        }
    }

    public (bool Success, CanFrame Frame, string Message) TryBuildCardFrame(Guid cardId)
    {
        var card = SymbolicCards.FirstOrDefault(x => x.Id == cardId);
        if (card is null)
        {
            return (false, default, "Card not found.");
        }

        var pairText = string.Join(";", card.Signals.Select(x => $"{x.Name}={x.ValueText}"));
        return TryBuildSymbolicFrame(card.MessageDisplay, pairText);
    }

    public void AddDecodeWatch(string displayName)
    {
        if (!_symbolicByDisplay.TryGetValue(displayName, out var msg))
        {
            return;
        }

        if (_decodeWatchIds.Add(msg.ArbitrationId))
        {
            DecodeWatchItems.Add(displayName);
        }
    }

    public void RemoveDecodeWatch(string displayName)
    {
        if (!_symbolicByDisplay.TryGetValue(displayName, out var msg))
        {
            return;
        }

        _decodeWatchIds.Remove(msg.ArbitrationId);
        _ = DecodeWatchItems.Remove(displayName);
    }

    public void ClearDecodeWatch()
    {
        _decodeWatchIds.Clear();
        DecodeWatchItems.Clear();
    }

    public void LoadReplayEntries(IReadOnlyList<ReplayEntry> entries)
    {
        _replayEntries.Clear();
        _replayEntries.AddRange(entries);
        ReplayRows.Clear();
        foreach (var entry in entries)
        {
            ReplayRows.Add(new ReplayEntryViewModel(
                Index: entry.Index,
                RelativeSeconds: entry.RelativeSeconds.ToString("F3"),
                ArbitrationIdHex: $"0x{entry.Frame.ArbitrationId:X}",
                DataHex: BitConverter.ToString(entry.Frame.Data.ToArray()).Replace("-", " ")
            ));
        }
    }

    public async Task ReplayAsync(CancellationToken cancellationToken)
    {
        if (Session is null || !Session.IsConnected || _replayEntries.Count == 0)
        {
            return;
        }

        ReplayRunning = true;
        try
        {
            var start = DateTimeOffset.UtcNow;
            foreach (var entry in _replayEntries)
            {
                cancellationToken.ThrowIfCancellationRequested();
                var due = start.AddSeconds(entry.RelativeSeconds);
                var delay = due - DateTimeOffset.UtcNow;
                if (delay > TimeSpan.Zero)
                {
                    await Task.Delay(delay, cancellationToken);
                }

                _ = await Session.SendAsync(entry.Frame, cancellationToken);
            }
        }
        finally
        {
            ReplayRunning = false;
        }
    }

    public bool AddTriggerRule(uint arbId, int byteIndex, TriggerOperator op, double threshold)
    {
        if (byteIndex < 0 || byteIndex > 63)
        {
            return false;
        }

        var id = Guid.NewGuid();
        var rule = new TriggerRule(id, arbId, byteIndex, op, threshold);
        _triggerRules[id] = rule;
        TriggerRows.Add(new TriggerRowViewModel
        {
            Id = id,
            ArbitrationIdHex = $"0x{arbId:X}",
            ByteIndex = byteIndex,
            Operator = op.ToString(),
            Threshold = threshold
        });
        return true;
    }

    public void RemoveTriggerRule(Guid id)
    {
        _triggerRules.Remove(id);
        var item = TriggerRows.FirstOrDefault(x => x.Id == id);
        if (item is not null)
        {
            TriggerRows.Remove(item);
        }
    }

    public async Task StartReadingAsync(CancellationToken cancellationToken)
    {
        if (Session is null)
        {
            return;
        }

        _traceStartUtc ??= DateTimeOffset.UtcNow;

        try
        {
            await foreach (var frame in Session.ReadFramesAsync(cancellationToken))
            {
                MessageCount++;
                var rel = frame.TimestampUtc - _traceStartUtc.Value;
                var relSeconds = $"{Math.Max(0, rel.TotalSeconds):F3}";
                var ts = frame.TimestampUtc.ToString("HH:mm:ss.fff");
                var dataHex = BitConverter.ToString(frame.Data.ToArray()).Replace("-", " ");
                var arbHex = $"0x{frame.ArbitrationId:X}";
                var decodedSignals = DbcDecoder.Decode(frame, _mergedDbc);

                foreach (var triggerRule in _triggerRules.Values)
                {
                    if (_triggerEvaluator.Evaluate(triggerRule, frame))
                    {
                        TriggerHitCount++;
                        var triggerRow = TriggerRows.FirstOrDefault(x => x.Id == triggerRule.Id);
                        if (triggerRow is not null)
                        {
                            triggerRow.HitCount++;
                        }
                    }
                }

                if (IsPaused)
                {
                    continue;
                }

                if (_pendingFrames.Count > _maxPendingFrames)
                {
                    if (_pendingFrames.TryDequeue(out _))
                    {
                        DroppedRenderFrameCount++;
                    }
                }

                _pendingFrames.Enqueue(new PendingRenderFrame(
                    frame.ArbitrationId,
                    ts,
                    relSeconds,
                    arbHex,
                    dataHex,
                    decodedSignals
                ));

                if (decodedSignals.Count > 0)
                {
                    foreach (var signal in decodedSignals)
                    {
                        _pendingDecodedRows.Enqueue(new DecodedRowViewModel(
                            Timestamp: ts,
                            MessageKey: signal.MessageName,
                            Signal: signal.SignalName,
                            Value: signal.Value
                        ));
                    }
                }

                ScheduleUiFlush();
            }
        }
        catch (OperationCanceledException)
        {
            DispatcherQueue?.TryEnqueue(() =>
            {
                if (StatusText != "Disconnected")
                {
                    StatusText = "Read loop stopped.";
                }
            });
        }
    }

    private void ScheduleUiFlush()
    {
        if (_flushScheduled || DispatcherQueue is null)
        {
            return;
        }

        _flushScheduled = true;
        DispatcherQueue.TryEnqueue(() =>
        {
            _flushScheduled = false;
            var sw = Stopwatch.StartNew();
            RenderQueueDepth = _pendingFrames.Count;
            RenderStride = SelectRenderStride(RenderQueueDepth);
            DecodeStride = SelectDecodeStride(RenderQueueDepth);

            var frameApplied = 0;
            var frameIndex = 0;
            while (frameApplied < 800 && _pendingFrames.TryDequeue(out var pending))
            {
                var renderThis = (frameIndex % RenderStride) == 0;
                if (renderThis)
                {
                    ApplyRaw(pending);
                    ApplyInspect(pending);
                }
                else
                {
                    SampledOutFrameCount++;
                }

                if ((frameIndex % DecodeStride) == 0)
                {
                    ApplyDecodedGroups(pending);
                }

                frameApplied++;
                frameIndex++;
            }

            var decodedAdded = 0;
            while (decodedAdded < 300 && _pendingDecodedRows.TryDequeue(out var decoded))
            {
                DecodedRows.Add(decoded);
                decodedAdded++;
            }
            while (DecodedRows.Count > 8_000)
            {
                DecodedRows.RemoveAt(0);
            }

            LastUiFlushMs = sw.Elapsed.TotalMilliseconds;

            if (!_pendingFrames.IsEmpty || !_pendingDecodedRows.IsEmpty)
            {
                ScheduleUiFlush();
            }
        });
    }

    private static int SelectRenderStride(int depth) => depth switch
    {
        > 20000 => 20,
        > 10000 => 10,
        > 5000 => 6,
        > 2000 => 3,
        > 1000 => 2,
        _ => 1
    };

    private static int SelectDecodeStride(int depth) => depth switch
    {
        > 20000 => 20,
        > 10000 => 10,
        > 5000 => 6,
        > 2000 => 3,
        _ => 1
    };

    private void ApplyRaw(PendingRenderFrame pending)
    {
        if (RawMode == DisplayRowMode.AllFrames)
        {
            RawRows.Add(RawRowViewModel.Create(pending.Timestamp, pending.RelativeSeconds, pending.ArbitrationIdHex, pending.DataHex));
            while (RawRows.Count > _maxRawRows)
            {
                RawRows.RemoveAt(0);
            }
            return;
        }

        if (_latestRawById.TryGetValue(pending.ArbitrationId, out var existing))
        {
            existing.Timestamp = pending.Timestamp;
            existing.RelativeSeconds = pending.RelativeSeconds;
            existing.DataHex = pending.DataHex;
        }
        else
        {
            var created = RawRowViewModel.Create(pending.Timestamp, pending.RelativeSeconds, pending.ArbitrationIdHex, pending.DataHex);
            _latestRawById[pending.ArbitrationId] = created;
            RawRows.Add(created);
        }
    }

    private void ApplyInspect(PendingRenderFrame pending)
    {
        var symbolic = pending.DecodedSignals.Count > 0
            ? string.Join("; ", pending.DecodedSignals.Select(x => $"{x.SignalName}={x.Value}"))
            : "(no DBC match)";

        if (InspectMode == DisplayRowMode.AllFrames)
        {
            InspectRows.Add(InspectRowViewModel.Create(
                pending.Timestamp,
                pending.RelativeSeconds,
                pending.ArbitrationIdHex,
                pending.DataHex,
                symbolic));
            while (InspectRows.Count > _maxInspectRows)
            {
                InspectRows.RemoveAt(0);
            }
            return;
        }

        if (_latestInspectById.TryGetValue(pending.ArbitrationId, out var existing))
        {
            existing.Timestamp = pending.Timestamp;
            existing.RelativeSeconds = pending.RelativeSeconds;
            existing.RawDataHex = pending.DataHex;
            existing.Symbolic = symbolic;
        }
        else
        {
            var created = InspectRowViewModel.Create(
                pending.Timestamp,
                pending.RelativeSeconds,
                pending.ArbitrationIdHex,
                pending.DataHex,
                symbolic);
            _latestInspectById[pending.ArbitrationId] = created;
            InspectRows.Add(created);
        }
    }

    private void ApplyDecodedGroups(PendingRenderFrame pending)
    {
        if (pending.DecodedSignals.Count == 0)
        {
            return;
        }

        if (_decodeWatchIds.Count > 0 && !_decodeWatchIds.Contains(pending.ArbitrationId))
        {
            return;
        }

        if (!_decodedGroupsById.TryGetValue(pending.ArbitrationId, out var group))
        {
            var firstSignal = pending.DecodedSignals[0];
            group = new DecodedMessageGroupViewModel
            {
                ArbitrationId = pending.ArbitrationId,
                Title = firstSignal.MessageName,
                ArbitrationIdHex = pending.ArbitrationIdHex
            };
            _decodedGroupsById[pending.ArbitrationId] = group;
            DecodedGroups.Add(group);
            while (DecodedGroups.Count > _maxDecodedMessageGroups)
            {
                var remove = DecodedGroups[0];
                DecodedGroups.RemoveAt(0);
                _decodedGroupsById.Remove(remove.ArbitrationId);
            }
        }

        group.Timestamp = pending.Timestamp;
        group.RelativeSeconds = pending.RelativeSeconds;

        foreach (var signal in pending.DecodedSignals)
        {
            if (!group.SignalByName.TryGetValue(signal.SignalName, out var signalRow))
            {
                signalRow = new DecodedSignalViewModel
                {
                    SignalName = signal.SignalName,
                    Unit = signal.Unit
                };
                group.SignalByName[signal.SignalName] = signalRow;
                group.SignalStats[signal.SignalName] = (signal.NumericValue, signal.NumericValue);
                group.Signals.Add(signalRow);
            }
            else
            {
                var stats = group.SignalStats[signal.SignalName];
                var min = stats.Min.HasValue ? Math.Min(stats.Min.Value, signal.NumericValue) : signal.NumericValue;
                var max = stats.Max.HasValue ? Math.Max(stats.Max.Value, signal.NumericValue) : signal.NumericValue;
                group.SignalStats[signal.SignalName] = (min, max);
            }

            var latest = group.SignalStats[signal.SignalName];
            signalRow.Value = signal.Value;
            signalRow.Minimum = latest.Min.HasValue ? latest.Min.Value.ToString("G4") : string.Empty;
            signalRow.Maximum = latest.Max.HasValue ? latest.Max.Value.ToString("G4") : string.Empty;
        }
    }

    private void RebuildMergedDbc()
    {
        _mergedDbc = DbcDatabase.Merge(_dbcByPath.Values);
    }

    private void RebuildDbcFileRows()
    {
        DbcFiles.Clear();
        foreach (var kvp in _dbcByPath.OrderBy(x => x.Key, StringComparer.OrdinalIgnoreCase))
        {
            DbcFiles.Add(new DbcFileRowViewModel
            {
                Path = kvp.Key,
                MessageCount = kvp.Value.MessagesByArbitrationId.Count
            });
        }
    }

    private void RebuildSymbolicOptions()
    {
        SymbolicMessageOptions.Clear();
        DecodeWatchOptions.Clear();
        _symbolicByDisplay.Clear();

        var ordered = _mergedDbc.MessagesByArbitrationId
            .OrderBy(x => x.Key)
            .Select(x => x.Value)
            .ToList();
        foreach (var message in ordered)
        {
            var display = $"{message.Name} ({message.ArbitrationId:X})";
            SymbolicMessageOptions.Add(display);
            DecodeWatchOptions.Add(display);
            _symbolicByDisplay[display] = message;
        }

        if (SymbolicCards.Count == 0 && SymbolicMessageOptions.Count > 0)
        {
            _ = AddSymbolicCard();
            return;
        }

        foreach (var card in SymbolicCards)
        {
            card.MessageOptions.Clear();
            foreach (var option in SymbolicMessageOptions)
            {
                card.MessageOptions.Add(option);
            }

            if (string.IsNullOrWhiteSpace(card.MessageDisplay) || !SymbolicMessageOptions.Contains(card.MessageDisplay))
            {
                if (SymbolicMessageOptions.Count > 0)
                {
                    SetCardMessage(card.Id, SymbolicMessageOptions[0]);
                }
            }
            else
            {
                SetCardMessage(card.Id, card.MessageDisplay);
            }
        }
    }

    private sealed record PendingRenderFrame(
        uint ArbitrationId,
        string Timestamp,
        string RelativeSeconds,
        string ArbitrationIdHex,
        string DataHex,
        IReadOnlyList<DecodedSignalValue> DecodedSignals
    );
}
