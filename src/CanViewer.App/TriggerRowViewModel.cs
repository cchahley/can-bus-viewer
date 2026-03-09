namespace CanViewer.App;

public sealed class TriggerRowViewModel
{
    public required Guid Id { get; init; }
    public required string ArbitrationIdHex { get; init; }
    public required int ByteIndex { get; init; }
    public required string Operator { get; init; }
    public required double Threshold { get; init; }
    public int HitCount { get; set; }
}
