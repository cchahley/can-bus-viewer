using CanViewer.Core.Models;

namespace CanViewer.Core.Buffers;

public sealed class BoundedFrameBuffer
{
    private readonly int _capacity;
    private readonly Queue<CanFrame> _items;
    private readonly object _gate = new();

    public BoundedFrameBuffer(int capacity)
    {
        if (capacity <= 0)
        {
            throw new ArgumentOutOfRangeException(nameof(capacity));
        }

        _capacity = capacity;
        _items = new Queue<CanFrame>(capacity);
    }

    public int Count
    {
        get
        {
            lock (_gate)
            {
                return _items.Count;
            }
        }
    }

    public long DroppedCount { get; private set; }

    public void Add(CanFrame frame)
    {
        lock (_gate)
        {
            if (_items.Count == _capacity)
            {
                _items.Dequeue();
                DroppedCount++;
            }

            _items.Enqueue(frame);
        }
    }

    public IReadOnlyList<CanFrame> Snapshot()
    {
        lock (_gate)
        {
            return _items.ToArray();
        }
    }

    public void Clear()
    {
        lock (_gate)
        {
            _items.Clear();
        }
    }
}
