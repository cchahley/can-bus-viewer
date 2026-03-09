namespace CanViewer.Core.Triggers;

public sealed record TriggerRule(
    Guid Id,
    uint ArbitrationId,
    int ByteIndex,
    TriggerOperator Operator,
    double Threshold
);
