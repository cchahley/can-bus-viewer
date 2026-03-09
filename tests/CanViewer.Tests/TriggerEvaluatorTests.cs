using CanViewer.Core.Models;
using CanViewer.Core.Triggers;

namespace CanViewer.Tests;

public class TriggerEvaluatorTests
{
    [Fact]
    public void Evaluate_EqualOperator_MatchesThreshold()
    {
        var evaluator = new TriggerEvaluator();
        var rule = new TriggerRule(Guid.NewGuid(), 0x123, 0, TriggerOperator.Equal, 3);
        var frame = NewFrame(0x123, 0x03, 0x10);

        Assert.True(evaluator.Evaluate(rule, frame));
    }

    [Fact]
    public void Evaluate_RisingOperator_TriggersOnCross()
    {
        var evaluator = new TriggerEvaluator();
        var rule = new TriggerRule(Guid.NewGuid(), 0x123, 0, TriggerOperator.Rising, 10);

        Assert.False(evaluator.Evaluate(rule, NewFrame(0x123, 5)));
        Assert.True(evaluator.Evaluate(rule, NewFrame(0x123, 10)));
    }

    private static CanFrame NewFrame(uint id, params byte[] bytes)
    {
        return new CanFrame(
            TimestampUtc: DateTimeOffset.UtcNow,
            ArbitrationId: id,
            Dlc: (byte)bytes.Length,
            Data: bytes
        );
    }
}
