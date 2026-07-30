using System;
using System.Diagnostics;
using System.IO;
using System.Runtime.InteropServices;
using System.Threading;

[assembly: System.Reflection.AssemblyTitle("MEHDORA Textile Studio")]
[assembly: System.Reflection.AssemblyProduct("MEHDORA Textile Studio")]
[assembly: System.Reflection.AssemblyCompany("ALI AHMAD TEXTILE")]
[assembly: System.Reflection.AssemblyCopyright("ALI AHMAD TEXTILE")]
[assembly: System.Reflection.AssemblyVersion("1.0.0.0")]

internal static class MehdoraLauncher
{
    [DllImport("user32.dll", CharSet = CharSet.Unicode)]
    private static extern bool SetWindowText(IntPtr hWnd, string text);

    [STAThread]
    private static int Main(string[] args)
    {
        string root = AppDomain.CurrentDomain.BaseDirectory;
        string engine = Path.Combine(root, "bin", "krita.exe");
        if (!File.Exists(engine))
        {
            System.Windows.Forms.MessageBox.Show(
                "MEHDORA engine files are incomplete.",
                "MEHDORA Textile Studio",
                System.Windows.Forms.MessageBoxButtons.OK,
                System.Windows.Forms.MessageBoxIcon.Error
            );
            return 2;
        }

        var start = new ProcessStartInfo
        {
            FileName = engine,
            WorkingDirectory = Path.GetDirectoryName(engine),
            UseShellExecute = false,
            Arguments = BuildArguments(args)
        };
        start.EnvironmentVariables["MEHDORA_BRAND"] = "MEHDORA Textile Studio";

        Process process = Process.Start(start);
        if (process == null)
        {
            return 3;
        }

        while (!process.HasExited)
        {
            process.Refresh();
            if (process.MainWindowHandle != IntPtr.Zero)
            {
                SetWindowText(process.MainWindowHandle, "MEHDORA Textile Studio");
            }
            Thread.Sleep(500);
        }
        return process.ExitCode;
    }

    private static string BuildArguments(string[] args)
    {
        if (args == null || args.Length == 0)
        {
            return "";
        }
        string[] escaped = new string[args.Length];
        for (int i = 0; i < args.Length; i++)
        {
            escaped[i] = "\"" + args[i].Replace("\"", "\\\"") + "\"";
        }
        return string.Join(" ", escaped);
    }
}
