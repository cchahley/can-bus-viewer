using CanViewer.Core.Models;

namespace CanViewer.Core.Triggers;

public sealed class TriggerEvaluator
{
    private readonly Dictionary<Guid, double> _previousValues = new();

    public bool Evaluate(TriggerRule rule, CanFrame frame)
    {
        if (frame.ArbitrationId != rule.ArbitrationId)
        {
            return false;
        }

        var data = frame.Data.Span;
        if (rule.ByteIndex < 0 || rule.ByteIndex >= data.Length)
        {
            return false;
        }

        var value = data[rule.ByteIndex];
        _previousValues.TryGetValue(rule.Id, out var previous);
        var hasPrevious = _previousValues.ContainsKey(rule.Id);
        _previousValues[rule.Id] = value;

        return rule.Operator switch
        {
            TriggerOperator.Equal => value == rule.Threshold,
            TriggerOperator.NotEqual => value != rule.Threshold,
            TriggerOperator.GreaterThan => value > rule.Threshold,
            TriggerOperator.GreaterOrEqual => value >= rule.Threshold,
            TriggerOperator.LessThan => value < rule.Threshold,
            TriggerOperator.LessOrEqual => value <= rule.Threshold,
            TriggerOperator.Changed => hasPrevious && value != previous,
            TriggerOperator.Rising => hasPrevious && previous < rule.Threshold && value >= rule.Threshold,
            TriggerOperator.Falling => hasPrevious && previous > rule.Threshold && value <= rule.Threshold,
            _ => false
        };
    }
}
