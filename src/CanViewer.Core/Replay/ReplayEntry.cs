using CanViewer.Core.Models;

namespace CanViewer.Core.Replay;

public readonly record struct ReplayEntry(
    int Index,
    double RelativeSeconds,
    CanFrame Frame
);
