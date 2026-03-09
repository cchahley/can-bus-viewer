using Microsoft.UI.Xaml;
using System.Text;

namespace CanViewer.App;

public partial class App : Application
{
    private Window? _window;
    private static readonly object LogLock = new();

    public App()
    {
        InitializeComponent();
        UnhandledException += OnUnhandledException;
        AppDomain.CurrentDomain.UnhandledException += OnDomainUnhandledException;
        TaskScheduler.UnobservedTaskException += OnUnobservedTaskException;
    }

    protected override void OnLaunched(LaunchActivatedEventArgs args)
    {
        _window = new MainWindow();
        _window.Activate();
    }

    private static void OnUnhandledException(object sender, Microsoft.UI.Xaml.UnhandledExceptionEventArgs e)
    {
        WriteCrashLog("XamlUnhandledException", e.Exception);
    }

    private static void OnDomainUnhandledException(object sender, System.UnhandledExceptionEventArgs e)
    {
        if (e.ExceptionObject is Exception ex)
        {
            WriteCrashLog("DomainUnhandledException", ex);
        }
    }

    private static void OnUnobservedTaskException(object? sender, UnobservedTaskExceptionEventArgs e)
    {
        WriteCrashLog("UnobservedTaskException", e.Exception);
    }

    private static void WriteCrashLog(string source, Exception ex)
    {
        try
        {
            var logPath = Path.Combine(AppContext.BaseDirectory, "canviewer_crash.log");
            var sb = new StringBuilder();
            sb.AppendLine($"[{DateTimeOffset.Now:O}] {source}");
            sb.AppendLine(ex.ToString());
            sb.AppendLine();
            lock (LogLock)
            {
                File.AppendAllText(logPath, sb.ToString());
            }
        }
        catch
        {
        }
    }
}
