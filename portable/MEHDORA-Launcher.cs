using System;
using System.Diagnostics;
using System.Drawing;
using System.IO;
using System.Runtime.InteropServices;
using System.Threading;
using System.Windows.Forms;

[assembly: System.Reflection.AssemblyTitle("MEHDORA Textile Studio")]
[assembly: System.Reflection.AssemblyProduct("MEHDORA Textile Studio")]
[assembly: System.Reflection.AssemblyCompany("ALI AHMAD TEXTILE")]
[assembly: System.Reflection.AssemblyCopyright("ALI AHMAD TEXTILE")]
[assembly: System.Reflection.AssemblyVersion("1.0.0.0")]

internal static class MehdoraLauncher
{
    [DllImport("user32.dll", CharSet = CharSet.Unicode)]
    private static extern bool SetWindowText(IntPtr hWnd, string text);

    [DllImport("user32.dll")]
    private static extern IntPtr SendMessage(
        IntPtr hWnd, uint message, IntPtr wParam, IntPtr lParam
    );

    private const uint WM_SETICON = 0x0080;
    private static Icon mehdoraIcon;

    [STAThread]
    private static int Main(string[] args)
    {
        string root = AppDomain.CurrentDomain.BaseDirectory;
        string engine = Path.Combine(root, "bin", "krita.exe");
        Form splash = CreateSplash(root);
        if (splash != null)
        {
            splash.Show();
            Application.DoEvents();
        }
        if (!File.Exists(engine))
        {
            if (splash != null) splash.Close();
            MessageBox.Show(
                "MEHDORA engine files are incomplete.",
                "MEHDORA Textile Studio",
                MessageBoxButtons.OK,
                MessageBoxIcon.Error
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
            if (splash != null) splash.Close();
            return 3;
        }

        bool mainWindowReady = false;
        while (!process.HasExited)
        {
            process.Refresh();
            if (process.MainWindowHandle != IntPtr.Zero)
            {
                if (!mainWindowReady)
                {
                    mainWindowReady = true;
                    if (splash != null)
                    {
                        splash.Close();
                        splash.Dispose();
                        splash = null;
                    }
                }
                SetWindowText(process.MainWindowHandle, "MEHDORA Textile Studio");
                ApplyMehdoraIcon(process.MainWindowHandle);
            }
            Application.DoEvents();
            Thread.Sleep(500);
        }
        if (splash != null)
        {
            splash.Close();
            splash.Dispose();
        }
        return process.ExitCode;
    }

    private static string BuildArguments(string[] args)
    {
        string startup = "--nosplash";
        if (args == null || args.Length == 0)
        {
            return startup + " --new-image RGBA,U8,1600,1000";
        }
        string[] escaped = new string[args.Length];
        for (int i = 0; i < args.Length; i++)
        {
            escaped[i] = "\"" + args[i].Replace("\"", "\\\"") + "\"";
        }
        return startup + " " + string.Join(" ", escaped);
    }

    private static void ApplyMehdoraIcon(IntPtr window)
    {
        if (mehdoraIcon == null)
        {
            Bitmap bitmap = new Bitmap(64, 64);
            using (Graphics graphics = Graphics.FromImage(bitmap))
            {
                graphics.Clear(Color.FromArgb(35, 35, 40));
                using (SolidBrush brush = new SolidBrush(Color.FromArgb(211, 160, 82)))
                using (Font font = new Font("Segoe UI", 38, FontStyle.Bold, GraphicsUnit.Pixel))
                {
                    StringFormat format = new StringFormat();
                    format.Alignment = StringAlignment.Center;
                    format.LineAlignment = StringAlignment.Center;
                    graphics.DrawString("M", font, brush, new RectangleF(0, 0, 64, 62), format);
                }
            }
            mehdoraIcon = Icon.FromHandle(bitmap.GetHicon());
        }
        SendMessage(window, WM_SETICON, new IntPtr(0), mehdoraIcon.Handle);
        SendMessage(window, WM_SETICON, new IntPtr(1), mehdoraIcon.Handle);
    }

    private static Form CreateSplash(string root)
    {
        string imagePath = Path.Combine(root, "MEHDORA-Splash.png");
        if (!File.Exists(imagePath))
        {
            return null;
        }
        Form form = new Form();
        form.FormBorderStyle = FormBorderStyle.None;
        form.StartPosition = FormStartPosition.CenterScreen;
        form.ClientSize = new Size(1000, 563);
        form.BackgroundImage = Image.FromFile(imagePath);
        form.BackgroundImageLayout = ImageLayout.Stretch;
        form.ShowInTaskbar = false;
        form.TopMost = true;
        form.BackColor = Color.FromArgb(24, 31, 35);
        return form;
    }
}
